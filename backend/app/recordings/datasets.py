from __future__ import annotations

import io
import json
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from ..api.errors import AppError, conflict, not_found
from ..database.models import DatasetMemberRow, DatasetRow, DerivativeRow, LabelRow, RecordingRow, SegmentRow, iso
from ..processing.repair import PRESETS
from ..processing.validation import rate_compatibility
from .library import APP_VERSION_TAG
from .storage import new_id, safe_token, utc_stamp


class DatasetService:
    def __init__(self, paths: Any, db: Any, library: Any, activity: Any, workspace_provider):
        self.paths = paths
        self.db = db
        self.library = library
        self.activity = activity
        self.workspace = workspace_provider

    def _get(self, db, dataset_id: str) -> DatasetRow:
        row = db.get(DatasetRow, dataset_id)
        if row is None or row.workspace != self.workspace():
            raise not_found("Dataset", dataset_id)
        return row

    def list(self) -> list[dict]:
        workspace = self.workspace()
        with self.db() as db:
            rows = db.scalars(select(DatasetRow).where(DatasetRow.workspace == workspace).order_by(DatasetRow.created_at.desc())).all()
            counts = dict(db.execute(select(DatasetMemberRow.dataset_id, func.count()).group_by(DatasetMemberRow.dataset_id)).all())
            out = []
            for r in rows:
                out.append({"dataset_id": r.dataset_id, "name": r.name, "description": r.description, "members": counts.get(r.dataset_id, 0), "created_at": iso(r.created_at), "workspace": r.workspace})
        for item in out:
            item["distribution"] = self.distribution(item["dataset_id"])["by_label"]
        return out

    def create(self, name: str, description: str = "") -> dict:
        name = name.strip()
        if not name:
            raise AppError("name_required", "Give the dataset a name", 422)
        with self.db.begin() as db:
            exists = db.scalar(select(DatasetRow).where(DatasetRow.workspace == self.workspace(), DatasetRow.name == name))
            if exists:
                raise conflict("dataset_exists", f"A dataset named '{name}' already exists")
            row = DatasetRow(dataset_id=new_id("ds", name), workspace=self.workspace(), name=name, description=description)
            db.add(row)
            db.flush()
            dataset_id = row.dataset_id
        self.activity.info("dataset", f"Created dataset {name}")
        return self.detail(dataset_id)

    def update(self, dataset_id: str, name: str | None, description: str | None) -> dict:
        with self.db.begin() as db:
            row = self._get(db, dataset_id)
            if name is not None and name.strip():
                row.name = name.strip()
            if description is not None:
                row.description = description
        return self.detail(dataset_id)

    def delete(self, dataset_id: str) -> dict:
        with self.db.begin() as db:
            row = self._get(db, dataset_id)
            db.query(DatasetMemberRow).filter(DatasetMemberRow.dataset_id == dataset_id).delete()
            db.delete(row)
        self.activity.info("dataset", f"Deleted dataset {dataset_id} (recordings untouched)")
        return {"dataset_id": dataset_id, "recordings_untouched": True}

    def _member_rows(self, db, dataset_id: str):
        return db.execute(
            select(DatasetMemberRow, RecordingRow, SegmentRow)
            .join(RecordingRow, RecordingRow.recording_id == DatasetMemberRow.recording_id)
            .outerjoin(SegmentRow, SegmentRow.segment_id == DatasetMemberRow.segment_id)
            .where(DatasetMemberRow.dataset_id == dataset_id)
        ).all()

    def members(self, dataset_id: str) -> list[dict]:
        with self.db() as db:
            self._get(db, dataset_id)
            names = self.library.label_names(db)
            out = []
            for member, rec, seg in self._member_rows(db, dataset_id):
                label = seg.label_id if seg is not None else rec.label_id
                needs_repair = rec.validation_state == "flagged" and member.derivative_id is None
                out.append({
                    "member_id": member.member_id,
                    "recording_id": rec.recording_id,
                    "segment_id": member.segment_id,
                    "derivative_id": member.derivative_id,
                    "label_id": label,
                    "label_name": names.get(label),
                    "kind": rec.kind,
                    "source": rec.source,
                    "sensor_id": rec.sensor_id,
                    "session_id": rec.session_id,
                    "duration_s": (seg.end_s - seg.start_s) if seg is not None else rec.duration_s,
                    "segment": {"start_s": seg.start_s, "end_s": seg.end_s} if seg is not None else None,
                    "fs_median_hz": rec.fs_median_hz,
                    "validation_state": rec.validation_state,
                    "needs_repair": needs_repair,
                    "usable": rec.validation_state == "valid" or (rec.validation_state == "flagged" and member.derivative_id is not None),
                })
        return out

    def detail(self, dataset_id: str) -> dict:
        with self.db() as db:
            row = self._get(db, dataset_id)
            base = {"dataset_id": row.dataset_id, "name": row.name, "description": row.description, "created_at": iso(row.created_at), "workspace": row.workspace}
        members = self.members(dataset_id)
        return {**base, "members": members, **self.distribution(dataset_id, members), "readiness": self.readiness(dataset_id, members)}

    def add_members(self, dataset_id: str, items: list[dict]) -> dict:
        added, skipped = 0, []
        with self.db.begin() as db:
            self._get(db, dataset_id)
            existing = {(m.recording_id, m.segment_id) for m in db.scalars(select(DatasetMemberRow).where(DatasetMemberRow.dataset_id == dataset_id)).all()}
            for item in items:
                recording_id = item.get("recording_id")
                segment_id = item.get("segment_id")
                derivative_id = item.get("derivative_id")
                rec = db.get(RecordingRow, recording_id)
                if rec is None or rec.workspace != self.workspace():
                    skipped.append({"recording_id": recording_id, "reason": "recording not found in this mode"})
                    continue
                if segment_id is None and rec.kind == "continuous":
                    segments = db.scalars(select(SegmentRow).where(SegmentRow.recording_id == recording_id)).all()
                    if not segments:
                        skipped.append({"recording_id": recording_id, "reason": "continuous recording has no labeled segments yet; annotate segments first"})
                        continue
                    for seg in segments:
                        if (recording_id, seg.segment_id) not in existing:
                            db.add(DatasetMemberRow(dataset_id=dataset_id, recording_id=recording_id, segment_id=seg.segment_id, derivative_id=derivative_id))
                            existing.add((recording_id, seg.segment_id))
                            added += 1
                    continue
                if segment_id is not None:
                    seg = db.get(SegmentRow, segment_id)
                    if seg is None or seg.recording_id != recording_id:
                        skipped.append({"recording_id": recording_id, "reason": f"segment {segment_id} does not belong to this recording"})
                        continue
                elif rec.label_id is None:
                    skipped.append({"recording_id": recording_id, "reason": "trial has no label"})
                    continue
                if derivative_id is not None:
                    d = db.get(DerivativeRow, derivative_id)
                    if d is None or d.recording_id != recording_id:
                        skipped.append({"recording_id": recording_id, "reason": "derivative does not belong to this recording"})
                        continue
                if (recording_id, segment_id) in existing:
                    skipped.append({"recording_id": recording_id, "reason": "already a member"})
                    continue
                db.add(DatasetMemberRow(dataset_id=dataset_id, recording_id=recording_id, segment_id=segment_id, derivative_id=derivative_id))
                existing.add((recording_id, segment_id))
                added += 1
        return {"added": added, "skipped": skipped, "dataset": self.detail(dataset_id)}

    def remove_members(self, dataset_id: str, member_ids: list[int]) -> dict:
        with self.db.begin() as db:
            self._get(db, dataset_id)
            removed = db.query(DatasetMemberRow).filter(DatasetMemberRow.dataset_id == dataset_id, DatasetMemberRow.member_id.in_(member_ids)).delete(synchronize_session=False)
        return {"removed": removed, "dataset": self.detail(dataset_id)}

    def set_member_derivative(self, dataset_id: str, member_id: int, derivative_id: str | None) -> dict:
        with self.db.begin() as db:
            self._get(db, dataset_id)
            member = db.get(DatasetMemberRow, member_id)
            if member is None or member.dataset_id != dataset_id:
                raise not_found("Dataset member", str(member_id))
            if derivative_id is not None:
                d = db.get(DerivativeRow, derivative_id)
                if d is None or d.recording_id != member.recording_id:
                    raise AppError("derivative_mismatch", "That derivative does not belong to this member's recording", 422)
            member.derivative_id = derivative_id
        return self.detail(dataset_id)

    def repair_flagged(self, dataset_id: str, recipe_name: str, confirm: bool) -> dict:
        if recipe_name not in PRESETS:
            raise AppError("unknown_recipe", f"Unknown recipe '{recipe_name}'", 422, {"presets": list(PRESETS)})
        if not confirm:
            raise conflict("confirmation_required", f"This creates '{recipe_name}' derivatives for every flagged member. Originals stay unchanged. Resend with confirm=true.")
        flagged = [m for m in self.members(dataset_id) if m["needs_repair"]]
        created: dict[str, str] = {}
        for member in flagged:
            rid = member["recording_id"]
            if rid not in created:
                created[rid] = self.library.create_derivative(rid, PRESETS[recipe_name])["derivative_id"]
            self.set_member_derivative(dataset_id, member["member_id"], created[rid])
        self.activity.info("dataset", f"Applied {recipe_name} to {len(created)} flagged recording(s) in dataset {dataset_id}")
        return {"recipe": recipe_name, "derivatives_created": len(created), "members_updated": len(flagged), "dataset": self.detail(dataset_id)}

    def distribution(self, dataset_id: str, members: list[dict] | None = None) -> dict:
        members = members if members is not None else self.members(dataset_id)
        by_label: dict[str, dict] = defaultdict(lambda: {"members": 0, "trials": 0, "segments": 0, "duration_s": 0.0, "recordings": set(), "sessions": set(), "sensors": set()})
        for m in members:
            entry = by_label[m["label_id"] or "unlabeled"]
            entry["members"] += 1
            entry["segments" if m["segment_id"] else "trials"] += 1
            entry["duration_s"] += m["duration_s"] or 0.0
            entry["recordings"].add(m["recording_id"])
            if m["session_id"]:
                entry["sessions"].add(m["session_id"])
            if m["sensor_id"]:
                entry["sensors"].add(m["sensor_id"])
        result = {}
        for label, entry in sorted(by_label.items()):
            result[label] = {
                "members": entry["members"],
                "trials": entry["trials"],
                "segments": entry["segments"],
                "duration_s": round(entry["duration_s"], 3),
                "recordings": len(entry["recordings"]),
                "sessions": len(entry["sessions"]),
                "sensors": sorted(entry["sensors"]),
            }
        rates = rate_compatibility([m["fs_median_hz"] for m in members])
        return {"by_label": result, "rate_check": rates, "member_count": len(members)}

    def readiness(self, dataset_id: str, members: list[dict] | None = None, idle_ids: set[str] | None = None) -> dict:
        members = members if members is not None else self.members(dataset_id)
        problems, warnings = [], []
        dist = self.distribution(dataset_id, members)
        labels = [label for label in dist["by_label"] if label != "unlabeled"]
        needs_repair = [m for m in members if m["needs_repair"]]
        invalid = [m for m in members if m["validation_state"] == "invalid"]
        if needs_repair:
            problems.append({"code": "needs_repair", "message": f"{len(needs_repair)} member(s) are flagged and have no repair derivative; apply an explicit recipe first", "count": len(needs_repair)})
        if invalid:
            problems.append({"code": "invalid_members", "message": f"{len(invalid)} member(s) failed validation; remove them", "count": len(invalid)})
        if len(labels) < 2:
            problems.append({"code": "too_few_classes", "message": "Training needs at least two labels", "count": len(labels)})
        idle_ids = idle_ids if idle_ids is not None else {"idle"}
        if not any(label in idle_ids for label in labels):
            problems.append({"code": "no_idle", "message": "Add Idle / No Gesture examples; the recognizer needs them to avoid unwanted actions", "count": 0})
        if not dist["rate_check"]["compatible"]:
            warnings.append({"code": "mixed_rates", "message": f"Members were sampled between {dist['rate_check']['min_hz']:.1f} and {dist['rate_check']['max_hz']:.1f} Hz; features may not be comparable"})
        no_session = [m for m in members if not m["session_id"]]
        if no_session:
            warnings.append({"code": "missing_sessions", "message": f"{len(no_session)} member(s) have no session; they are grouped by recording during evaluation, which can be optimistic"})
        for label, info in dist["by_label"].items():
            groups = info["sessions"] if info["sessions"] else info["recordings"]
            if groups < 2:
                warnings.append({"code": "few_groups", "message": f"'{label}' comes from only {groups} session/recording group; grouped evaluation will report insufficient data"})
        return {"ready": not problems, "problems": problems, "warnings": warnings}

    def export(self, dataset_id: str) -> Path:
        detail = self.detail(dataset_id)
        workspace = self.workspace()
        name = f"{safe_token(detail['name'], 'dataset')}_{utc_stamp()}.zip"
        target = self.paths.exports_dir(workspace) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "dataset": {k: detail[k] for k in ("dataset_id", "name", "description", "created_at", "workspace")},
            "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "app": APP_VERSION_TAG,
            "units": {"accel": "g", "gyro": "deg/s", "time": "us"},
            "members": [],
        }
        with self.db() as db:
            recordings = {r.recording_id: r for r in db.scalars(select(RecordingRow).where(RecordingRow.recording_id.in_({m["recording_id"] for m in detail["members"]}))).all()}
            derivatives = {d.derivative_id: d for d in db.scalars(select(DerivativeRow).where(DerivativeRow.recording_id.in_(list(recordings)))).all()}
        with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            written: set[str] = set()
            for m in detail["members"]:
                rec = recordings[m["recording_id"]]
                raw_name = f"raw/{rec.recording_id}.csv"
                if raw_name not in written:
                    path = self.library.path_for(rec)
                    if path.is_file():
                        archive.write(path, raw_name)
                        written.add(raw_name)
                derivative_name = None
                if m["derivative_id"] and m["derivative_id"] in derivatives:
                    d = derivatives[m["derivative_id"]]
                    derivative_name = f"derived/{d.derivative_id}.csv"
                    if derivative_name not in written:
                        dpath = self.paths.resolve("data", d.file_path)
                        if dpath.is_file():
                            archive.write(dpath, derivative_name)
                            written.add(derivative_name)
                manifest["members"].append({
                    **m,
                    "raw_file": raw_name,
                    "derived_file": derivative_name,
                    "sha256": rec.sha256,
                    "provenance": rec.provenance,
                })
            archive.writestr("manifest.json", json.dumps(manifest, indent=2, default=str))
            labels = io.StringIO()
            labels.write("label_id,display_name\n")
            with self.db() as db:
                for row in db.scalars(select(LabelRow)).all():
                    labels.write(f"{row.label_id},{row.display_name}\n")
            archive.writestr("labels.csv", labels.getvalue())
        self.activity.info("dataset", f"Exported dataset {detail['name']} to {target.name}")
        return target
