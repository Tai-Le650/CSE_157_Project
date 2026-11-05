from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

from ..api.errors import AppError, conflict, not_found
from ..database.models import LabelRow, MappingRow, ProfileRow, iso
from ..recordings.storage import new_id
from .actions import describe_action, parse_gesture_action


class MappingService:
    def __init__(self, db: Any, settings: Any, labels: Any, activity: Any, on_change=None):
        self.db = db
        self.settings = settings
        self.labels = labels
        self.activity = activity
        self.on_change = on_change

    def _changed(self, profile_id: str) -> None:
        if self.on_change and profile_id == self.settings.current.active_profile_id:
            self.on_change(profile_id)

    def _profile_dict(self, db, row: ProfileRow) -> dict:
        names = {r.label_id: r.display_name for r in db.scalars(select(LabelRow)).all()}
        mappings = db.scalars(select(MappingRow).where(MappingRow.profile_id == row.profile_id).order_by(MappingRow.label_id)).all()
        return {
            "profile_id": row.profile_id,
            "name": row.name,
            "description": row.description,
            "read_only": row.read_only,
            "active": row.profile_id == self.settings.current.active_profile_id,
            "created_at": iso(row.created_at),
            "mappings": [
                {
                    "mapping_id": m.mapping_id,
                    "label_id": m.label_id,
                    "label_name": names.get(m.label_id),
                    "label_exists": m.label_id in names,
                    "action": m.action,
                    "description": self._describe(m.action),
                    "enabled": m.enabled,
                }
                for m in mappings
            ],
        }

    def _describe(self, action: dict) -> str:
        try:
            return describe_action(parse_gesture_action(action))
        except ValidationError:
            return "Invalid action (blocked)"

    def _get(self, db, profile_id: str) -> ProfileRow:
        row = db.get(ProfileRow, profile_id)
        if row is None:
            raise not_found("Profile", profile_id)
        return row

    def profiles(self) -> list[dict]:
        with self.db() as db:
            return [self._profile_dict(db, r) for r in db.scalars(select(ProfileRow).order_by(ProfileRow.created_at)).all()]

    def profile(self, profile_id: str) -> dict:
        with self.db() as db:
            return self._profile_dict(db, self._get(db, profile_id))

    def create_profile(self, name: str, description: str = "", copy_from: str | None = None) -> dict:
        with self.db.begin() as db:
            profile_id = new_id("prof", name)
            db.add(ProfileRow(profile_id=profile_id, name=name.strip() or "Profile", description=description, read_only=False))
            db.flush()
            if copy_from:
                source = self._get(db, copy_from)
                for m in db.scalars(select(MappingRow).where(MappingRow.profile_id == source.profile_id)).all():
                    db.add(MappingRow(profile_id=profile_id, label_id=m.label_id, action=dict(m.action), enabled=False))
        self.activity.info("mappings", f"Created mapping profile {name}" + (f" (copied from {copy_from}; entries disabled until reviewed)" if copy_from else ""))
        return self.profile(profile_id)

    def update_profile(self, profile_id: str, name: str | None, description: str | None) -> dict:
        with self.db.begin() as db:
            row = self._get(db, profile_id)
            if row.read_only:
                raise conflict("profile_read_only", "This profile is preserved read-only; duplicate it to make changes")
            if name is not None and name.strip():
                row.name = name.strip()
            if description is not None:
                row.description = description
        return self.profile(profile_id)

    def delete_profile(self, profile_id: str) -> None:
        with self.db.begin() as db:
            row = self._get(db, profile_id)
            if row.read_only:
                raise conflict("profile_read_only", "Preserved profiles cannot be deleted")
            db.query(MappingRow).filter(MappingRow.profile_id == profile_id).delete()
            db.delete(row)
        if self.settings.current.active_profile_id == profile_id:
            self.settings.update({"active_profile_id": None})
            self._changed(profile_id)

    def set_active(self, profile_id: str | None) -> dict:
        if profile_id is not None:
            with self.db() as db:
                self._get(db, profile_id)
        previous = self.settings.current.active_profile_id
        self.settings.update({"active_profile_id": profile_id})
        if self.on_change and previous != profile_id:
            self.on_change(profile_id)
        self.activity.info("mappings", f"Active mapping profile: {profile_id or 'none'}")
        return {"active_profile_id": profile_id}

    def upsert(self, profile_id: str, label_id: str, action: dict, enabled: bool) -> dict:
        try:
            parsed = parse_gesture_action(action)
        except ValidationError as exc:
            raise AppError("action_not_allowed", "That action is not on the allowlist", 422, [{"loc": [str(p) for p in e["loc"]], "msg": e["msg"]} for e in exc.errors()])
        if label_id in self.labels.idle_ids():
            raise AppError("idle_cannot_map", "Idle / No Gesture never triggers an action", 422)
        if not self.labels.exists(label_id):
            raise not_found("Label", label_id)
        with self.db.begin() as db:
            row = self._get(db, profile_id)
            if row.read_only:
                raise conflict("profile_read_only", "This profile is preserved read-only; duplicate it to make changes")
            existing = db.scalar(select(MappingRow).where(MappingRow.profile_id == profile_id, MappingRow.label_id == label_id))
            if existing is None:
                db.add(MappingRow(profile_id=profile_id, label_id=label_id, action=parsed.model_dump(), enabled=enabled))
            else:
                existing.action = parsed.model_dump()
                existing.enabled = enabled
        self._changed(profile_id)
        return self.profile(profile_id)

    def remove(self, profile_id: str, label_id: str) -> dict:
        with self.db.begin() as db:
            row = self._get(db, profile_id)
            if row.read_only:
                raise conflict("profile_read_only", "This profile is preserved read-only")
            db.query(MappingRow).filter(MappingRow.profile_id == profile_id, MappingRow.label_id == label_id).delete()
        self._changed(profile_id)
        return self.profile(profile_id)

    def action_for(self, label_id: str) -> dict | None:
        profile_id = self.settings.current.active_profile_id
        if not profile_id or label_id in self.labels.idle_ids():
            return None
        with self.db() as db:
            m = db.scalar(select(MappingRow).where(MappingRow.profile_id == profile_id, MappingRow.label_id == label_id, MappingRow.enabled.is_(True)))
            return dict(m.action) if m else None

    def enabled_count(self) -> int:
        profile_id = self.settings.current.active_profile_id
        if not profile_id:
            return 0
        with self.db() as db:
            return len(db.scalars(select(MappingRow).where(MappingRow.profile_id == profile_id, MappingRow.enabled.is_(True))).all())

    def simulate(self, label_id: str | None, action: dict | None) -> dict:
        if action is None:
            if label_id is None:
                raise AppError("label_or_action_required", "Provide a label or an action", 422)
            action = self.action_for(label_id)
            if action is None:
                return {"label_id": label_id, "mapped": False, "description": "No enabled mapping in the active profile", "executed": False, "simulated": True}
        try:
            parsed = parse_gesture_action(action)
        except ValidationError:
            raise AppError("action_not_allowed", "That action is not on the allowlist", 422)
        return {"label_id": label_id, "mapped": True, "action": parsed.model_dump(), "description": f"Would {describe_action(parsed)[0].lower()}{describe_action(parsed)[1:]}", "executed": False, "simulated": True}
