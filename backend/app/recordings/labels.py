from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select

from ..api.errors import AppError, conflict, not_found
from ..database.models import LabelChangeRow, LabelRow, MappingRow, RecordingRow, SegmentRow, iso

NEW_LABEL_RE = re.compile(r"^[a-z0-9_]{1,48}$")
LEGACY_LABEL_RE = re.compile(r"^[A-Za-z0-9_]{1,48}$")


class LabelService:
    def __init__(self, db: Any, activity: Any, workspace_provider):
        self.db = db
        self.activity = activity
        self.workspace = workspace_provider

    def _dict(self, row: LabelRow, rec_counts: dict, seg_counts: dict) -> dict:
        return {
            "label_id": row.label_id,
            "display_name": row.display_name,
            "enabled": row.enabled,
            "builtin": row.builtin,
            "is_idle": row.is_idle,
            "description": row.description,
            "recordings": rec_counts.get(row.label_id, 0),
            "segments": seg_counts.get(row.label_id, 0),
            "created_at": iso(row.created_at),
        }

    def list(self) -> list[dict]:
        workspace = self.workspace()
        with self.db() as db:
            rows = db.scalars(select(LabelRow).order_by(LabelRow.builtin.desc(), LabelRow.label_id)).all()
            rec_counts = dict(db.execute(select(RecordingRow.label_id, func.count()).where(RecordingRow.workspace == workspace).group_by(RecordingRow.label_id)).all())
            seg_counts = dict(
                db.execute(
                    select(SegmentRow.label_id, func.count()).join(RecordingRow, RecordingRow.recording_id == SegmentRow.recording_id).where(RecordingRow.workspace == workspace).group_by(SegmentRow.label_id)
                ).all()
            )
            order = {"idle": 0, "swipe_left": 1, "swipe_right": 2, "wrist_rotation": 3}
            items = [self._dict(r, rec_counts, seg_counts) for r in rows]
        return sorted(items, key=lambda i: (not i["enabled"], order.get(i["label_id"], 50), i["label_id"]))

    def idle_ids(self) -> set[str]:
        with self.db() as db:
            return set(db.scalars(select(LabelRow.label_id).where(LabelRow.is_idle.is_(True))).all())

    def create(self, label_id: str, display_name: str, enabled: bool = True, description: str = "") -> dict:
        if not NEW_LABEL_RE.match(label_id):
            raise AppError("invalid_label_id", "Label IDs use 1-48 lowercase letters, digits or underscores (for example 'thumbs_up')", 422)
        with self.db.begin() as db:
            if db.get(LabelRow, label_id) is not None:
                raise conflict("label_exists", f"Label '{label_id}' already exists")
            row = LabelRow(label_id=label_id, display_name=display_name.strip() or label_id, enabled=enabled, builtin=False, description=description)
            db.add(row)
            db.add(LabelChangeRow(action="create", label_id=label_id, details={"display_name": row.display_name}))
        self.activity.info("labels", f"Created label {label_id}")
        return next(i for i in self.list() if i["label_id"] == label_id)

    def ensure_legacy(self, label_id: str) -> None:
        if not LEGACY_LABEL_RE.match(label_id):
            raise AppError("invalid_label_id", f"Legacy label '{label_id}' is not a valid identifier", 422)
        with self.db.begin() as db:
            if db.get(LabelRow, label_id) is None:
                db.add(LabelRow(label_id=label_id, display_name=label_id.replace("_", " ").title(), enabled=True, builtin=False, description="Created from a legacy CLI file name"))
                db.add(LabelChangeRow(action="create_from_legacy", label_id=label_id, details={}))

    def update(self, label_id: str, display_name: str | None = None, enabled: bool | None = None, description: str | None = None) -> dict:
        with self.db.begin() as db:
            row = db.get(LabelRow, label_id)
            if row is None:
                raise not_found("Label", label_id)
            if enabled is False and row.is_idle:
                raise conflict("idle_required", "Idle / No Gesture cannot be disabled; it is the class that never triggers actions")
            changes = {}
            if display_name is not None and display_name.strip():
                changes["display_name"] = [row.display_name, display_name.strip()]
                row.display_name = display_name.strip()
            if enabled is not None and enabled != row.enabled:
                changes["enabled"] = [row.enabled, enabled]
                row.enabled = enabled
            if description is not None:
                row.description = description
            if changes:
                db.add(LabelChangeRow(action="update", label_id=label_id, details=changes))
        return next(i for i in self.list() if i["label_id"] == label_id)

    def rename(self, label_id: str, new_label_id: str, confirm: bool) -> dict:
        if not confirm:
            raise conflict("confirmation_required", "Renaming a label ID rewrites every recording, segment and mapping that uses it. Resend with confirm=true.")
        if not NEW_LABEL_RE.match(new_label_id):
            raise AppError("invalid_label_id", "Label IDs use lowercase letters, digits or underscores", 422)
        with self.db.begin() as db:
            row = db.get(LabelRow, label_id)
            if row is None:
                raise not_found("Label", label_id)
            if row.builtin:
                raise conflict("builtin_label", "Built-in label IDs are fixed (existing CLI files and models depend on them). Change the display name instead, or merge explicitly.")
            if db.get(LabelRow, new_label_id) is not None:
                raise conflict("label_exists", f"Label '{new_label_id}' already exists; use merge to combine labels")
            db.add(LabelRow(label_id=new_label_id, display_name=row.display_name, enabled=row.enabled, builtin=False, is_idle=row.is_idle, description=row.description))
            db.flush()
            moved = self._move_references(db, label_id, new_label_id)
            db.delete(row)
            db.add(LabelChangeRow(action="rename", label_id=new_label_id, details={"from": label_id, **moved}))
        self.activity.warning("labels", f"Renamed label {label_id} → {new_label_id}", **moved)
        return next(i for i in self.list() if i["label_id"] == new_label_id)

    def merge(self, source_id: str, target_id: str, confirm: bool) -> dict:
        if not confirm:
            raise conflict("confirmation_required", f"Merging moves every '{source_id}' recording and segment to '{target_id}'. Labels are never merged implicitly. Resend with confirm=true.")
        if source_id == target_id:
            raise AppError("same_label", "Choose two different labels", 422)
        with self.db.begin() as db:
            source = db.get(LabelRow, source_id)
            target = db.get(LabelRow, target_id)
            if source is None:
                raise not_found("Label", source_id)
            if target is None:
                raise not_found("Label", target_id)
            if source.is_idle:
                raise conflict("idle_required", "Idle cannot be merged away")
            moved = self._move_references(db, source_id, target_id, drop_mappings=True)
            source.enabled = False
            db.add(LabelChangeRow(action="merge", label_id=target_id, details={"from": source_id, **moved}))
        self.activity.warning("labels", f"Merged label {source_id} into {target_id}", **moved)
        return {"source": source_id, "target": target_id, **moved}

    def _move_references(self, db, old: str, new: str, drop_mappings: bool = False) -> dict:
        recordings = db.query(RecordingRow).filter(RecordingRow.label_id == old).update({RecordingRow.label_id: new})
        segments = db.query(SegmentRow).filter(SegmentRow.label_id == old).update({SegmentRow.label_id: new})
        if drop_mappings:
            mappings = db.query(MappingRow).filter(MappingRow.label_id == old).delete()
        else:
            mappings = db.query(MappingRow).filter(MappingRow.label_id == old).update({MappingRow.label_id: new})
        return {"recordings": recordings, "segments": segments, "mappings": mappings}

    def delete(self, label_id: str) -> None:
        with self.db.begin() as db:
            row = db.get(LabelRow, label_id)
            if row is None:
                raise not_found("Label", label_id)
            if row.builtin:
                raise conflict("builtin_label", "Built-in labels cannot be deleted; disable them instead")
            used = db.scalar(select(func.count()).select_from(RecordingRow).where(RecordingRow.label_id == label_id)) or 0
            used += db.scalar(select(func.count()).select_from(SegmentRow).where(SegmentRow.label_id == label_id)) or 0
            if used:
                raise conflict("label_in_use", f"Label '{label_id}' is used by {used} recording(s)/segment(s); relabel or merge them first")
            db.query(MappingRow).filter(MappingRow.label_id == label_id).delete()
            db.delete(row)
            db.add(LabelChangeRow(action="delete", label_id=label_id, details={}))

    def history(self, limit: int = 100) -> list[dict]:
        with self.db() as db:
            rows = db.scalars(select(LabelChangeRow).order_by(LabelChangeRow.change_id.desc()).limit(limit)).all()
            return [{"at": iso(r.at), "action": r.action, "label_id": r.label_id, "details": r.details} for r in rows]

    def enabled_ids(self) -> set[str]:
        with self.db() as db:
            return set(db.scalars(select(LabelRow.label_id).where(LabelRow.enabled.is_(True))).all())

    def exists(self, label_id: str) -> bool:
        with self.db() as db:
            return db.get(LabelRow, label_id) is not None
