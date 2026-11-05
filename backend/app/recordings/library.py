from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
from sqlalchemy import func, or_, select

from ..api.errors import AppError, conflict, not_found
from ..database.models import DatasetMemberRow, DatasetRow, DerivativeRow, LabelRow, RecordingRow, SegmentRow, SessionRow, iso
from ..processing.csv_io import AXES, ImuTable, magnitude, read_imu_csv
from ..processing.repair import RepairRecipe, apply_recipe
from ..processing.timeline import timeline_seconds
from ..processing.timestamps import EXCLUDED_FLAGS, FLAG_DUPLICATE, FLAG_GLITCH, classify_timestamps
from ..processing.validation import validate_table
from .storage import new_id, read_json, sha256_file, write_derivative_csv, write_json

APP_VERSION_TAG = "gesture-to-pc/1.0.0"


@dataclass
class LoadedSignal:
    t_us: np.ndarray
    values: np.ndarray
    epoch: np.ndarray
    timeline_s: np.ndarray
    uniform: bool
    fs_hz: float | None
    source: str
    segment: np.ndarray | None = None


def decimate(n: int, max_points: int) -> np.ndarray:
    if n <= max_points:
        return np.arange(n)
    return np.unique(np.linspace(0, n - 1, max_points).astype(np.int64))


class RecordingLibrary:
    def __init__(self, paths: Any, db: Any, hub: Any, activity: Any, workspace_provider: Callable[[], str]):
        self.paths = paths
        self.db = db
        self.hub = hub
        self.activity = activity
        self.workspace = workspace_provider

    def app_owned(self, row: RecordingRow) -> bool:
        return row.storage_base == "data" and (row.file_path.startswith("raw/") or row.file_path.startswith("processed/"))

    def path_for(self, row: RecordingRow) -> Path:
        return self.paths.resolve(row.storage_base, row.file_path)

    def to_dict(self, row: RecordingRow, label_names: dict | None = None, include_validation: bool = False) -> dict:
        report = row.validation or {}
        out = {
            "recording_id": row.recording_id,
            "workspace": row.workspace,
            "kind": row.kind,
            "source": row.source,
            "label_id": row.label_id,
            "label_name": (label_names or {}).get(row.label_id) if row.label_id else None,
            "sensor_id": row.sensor_id,
            "sensor_hand": row.sensor_hand,
            "session_id": row.session_id,
            "capture_id": row.capture_id,
            "start_time": iso(row.start_time),
            "device_t0_us": row.device_t0_us,
            "duration_s": row.duration_s,
            "sample_count": row.sample_count,
            "fs_median_hz": row.fs_median_hz,
            "fs_mean_hz": row.fs_mean_hz,
            "file": {"base": row.storage_base, "path": row.file_path, "absolute": str(self.path_for(row)), "size_bytes": row.size_bytes},
            "sha256": row.sha256,
            "header_alias": row.header_alias,
            "time_unit": row.time_unit,
            "units": {"accel": row.accel_unit, "gyro": row.gyro_unit, "time": "us"},
            "firmware_header": row.firmware_header,
            "validation_state": row.validation_state,
            "issues": [i for i in report.get("issues", []) if i.get("severity") != "info"],
            "measured_invalid": report.get("measured_invalid", {}).get("total"),
            "estimated_dropped": report.get("estimated_dropped", {}).get("samples"),
            "notes": row.notes,
            "provenance": row.provenance,
            "source_changed": row.source_changed,
            "app_owned": self.app_owned(row),
            "created_at": iso(row.created_at),
        }
        if include_validation:
            out["validation"] = report
        return out

    def label_names(self, db) -> dict:
        return {r.label_id: r.display_name for r in db.scalars(select(LabelRow)).all()}

    def get_row(self, db, recording_id: str) -> RecordingRow:
        row = db.get(RecordingRow, recording_id)
        if row is None or row.workspace != self.workspace():
            raise not_found("Recording", recording_id)
        return row

    def query(
        self,
        q: str | None = None,
        label_id: str | None = None,
        sensor_id: str | None = None,
        kind: str | None = None,
        source: str | None = None,
        state: str | None = None,
        session_id: str | None = None,
        sort: str = "created_desc",
        limit: int = 200,
        offset: int = 0,
    ) -> dict:
        with self.db() as db:
            stmt = select(RecordingRow).where(RecordingRow.workspace == self.workspace())
            if q:
                like = f"%{q}%"
                stmt = stmt.where(or_(RecordingRow.recording_id.like(like), RecordingRow.notes.like(like), RecordingRow.label_id.like(like), RecordingRow.sensor_id.like(like), RecordingRow.file_path.like(like)))
            for column, value in ((RecordingRow.label_id, label_id), (RecordingRow.sensor_id, sensor_id), (RecordingRow.kind, kind), (RecordingRow.source, source), (RecordingRow.validation_state, state), (RecordingRow.session_id, session_id)):
                if value:
                    stmt = stmt.where(column == value)
            total = db.scalar(select(func.count()).select_from(stmt.subquery()))
            order = {
                "created_desc": RecordingRow.created_at.desc(),
                "created_asc": RecordingRow.created_at.asc(),
                "duration_desc": RecordingRow.duration_s.desc(),
                "label": RecordingRow.label_id.asc(),
            }.get(sort, RecordingRow.created_at.desc())
            rows = db.scalars(stmt.order_by(order).limit(limit).offset(offset)).all()
            names = self.label_names(db)
            segment_counts = dict(db.execute(select(SegmentRow.recording_id, func.count()).group_by(SegmentRow.recording_id)).all())
            derivative_counts = dict(db.execute(select(DerivativeRow.recording_id, func.count()).group_by(DerivativeRow.recording_id)).all())
            items = []
            for row in rows:
                item = self.to_dict(row, names)
                item["segment_count"] = segment_counts.get(row.recording_id, 0)
                item["derivative_count"] = derivative_counts.get(row.recording_id, 0)
                items.append(item)
        return {"items": items, "total": total or 0, "limit": limit, "offset": offset}

    def detail(self, recording_id: str) -> dict:
        with self.db() as db:
            row = self.get_row(db, recording_id)
            names = self.label_names(db)
            out = self.to_dict(row, names, include_validation=True)
            out["segments"] = [self.segment_dict(s, names) for s in db.scalars(select(SegmentRow).where(SegmentRow.recording_id == recording_id).order_by(SegmentRow.start_s)).all()]
            out["derivatives"] = [self.derivative_dict(d) for d in db.scalars(select(DerivativeRow).where(DerivativeRow.recording_id == recording_id).order_by(DerivativeRow.created_at)).all()]
            datasets = db.execute(
                select(DatasetRow.dataset_id, DatasetRow.name).join(DatasetMemberRow, DatasetMemberRow.dataset_id == DatasetRow.dataset_id).where(DatasetMemberRow.recording_id == recording_id).distinct()
            ).all()
            out["datasets"] = [{"dataset_id": d, "name": n} for d, n in datasets]
        out["file_exists"] = Path(out["file"]["absolute"]).is_file()
        return out

    def read_table(self, row: RecordingRow) -> ImuTable:
        path = self.path_for(row)
        if not path.is_file():
            raise AppError("file_missing", f"The recording file is missing: {path}", 410)
        return read_imu_csv(path, time_unit=row.time_unit if row.header_alias == "time" else None)

    def raw_signal(self, row: RecordingRow) -> LoadedSignal:
        table = self.read_table(row)
        analysis = classify_timestamps(table.t_us, valid=table.valid_rows)
        good = analysis.good_mask & table.valid_rows
        t = analysis.t_us[good]
        epoch = analysis.epoch[good].astype(np.int64)
        return LoadedSignal(
            t_us=t,
            values=table.values[good],
            epoch=epoch,
            timeline_s=timeline_seconds(t, epoch),
            uniform=False,
            fs_hz=analysis.fs_median_hz(),
            source="raw",
        )

    def derivative_signal(self, d: DerivativeRow) -> LoadedSignal:
        path = self.paths.resolve("data", d.file_path)
        if not path.is_file():
            raise AppError("file_missing", f"The derivative file is missing: {path}", 410)
        table = read_imu_csv(path)
        epoch = table.epoch.astype(np.int64) if table.epoch is not None else np.zeros(table.n, dtype=np.int64)
        segment = table.segment.astype(np.int64) if table.segment is not None else None
        return LoadedSignal(
            t_us=table.t_us,
            values=table.values,
            epoch=epoch,
            timeline_s=timeline_seconds(table.t_us, epoch),
            uniform=d.uniform,
            fs_hz=d.fs_hz,
            source=f"derivative:{d.derivative_id}",
            segment=segment,
        )

    def signal_for(self, recording_id: str, derivative_id: str | None = None, allow_flagged_raw: bool = False) -> tuple[RecordingRow, LoadedSignal]:
        with self.db() as db:
            row = self.get_row(db, recording_id)
            if derivative_id:
                d = db.get(DerivativeRow, derivative_id)
                if d is None or d.recording_id != recording_id:
                    raise not_found("Derivative", derivative_id)
                return row, self.derivative_signal(d)
        if row.validation_state == "invalid":
            raise conflict("recording_invalid", "This recording failed validation and cannot be used", {"issues": row.validation.get("issues", [])})
        if row.validation_state == "flagged" and not allow_flagged_raw:
            raise conflict(
                "repair_required",
                "This recording is flagged. Choose an explicit repair recipe (or an existing derivative) before analysis or training.",
                {"issues": [i for i in row.validation.get("issues", []) if i["severity"] == "repair_required"]},
            )
        return row, self.raw_signal(row)

    def preview(self, recording_id: str, max_points: int = 2500, derivative_id: str | None = None) -> dict:
        with self.db() as db:
            row = self.get_row(db, recording_id)
            names = self.label_names(db)
            segments = [self.segment_dict(s, names) for s in db.scalars(select(SegmentRow).where(SegmentRow.recording_id == recording_id).order_by(SegmentRow.start_s)).all()]
            d = db.get(DerivativeRow, derivative_id) if derivative_id else None
            if derivative_id and (d is None or d.recording_id != recording_id):
                raise not_found("Derivative", derivative_id)
        markers = []
        if d is not None:
            signal = self.derivative_signal(d)
        else:
            table = self.read_table(row)
            analysis = classify_timestamps(table.t_us, valid=table.valid_rows)
            good = analysis.good_mask & table.valid_rows
            t = analysis.t_us[good]
            epoch = analysis.epoch[good].astype(np.int64)
            timeline = timeline_seconds(t, epoch)
            signal = LoadedSignal(t, table.values[good], epoch, timeline, False, analysis.fs_median_hz(), "raw")
            good_index = np.flatnonzero(good)
            for i in np.flatnonzero((analysis.flags & (FLAG_GLITCH | FLAG_DUPLICATE)) != 0)[:200]:
                pos = int(np.searchsorted(good_index, i))
                ref = min(max(pos - 1, 0), len(timeline) - 1) if len(timeline) else None
                if ref is not None:
                    markers.append({"t_s": float(timeline[ref]), "kind": "glitch" if analysis.flags[i] & FLAG_GLITCH else "duplicate", "row": int(i)})
            for i in np.flatnonzero(~table.valid_rows)[:200]:
                markers.append({"t_s": None, "kind": "invalid_row", "row": int(i)})
        idx = decimate(len(signal.t_us), max_points)
        values = signal.values[idx]
        channels = {axis: values[:, i].tolist() for i, axis in enumerate(AXES)}
        channels["amag"] = magnitude(values, "accel").tolist()
        channels["gmag"] = magnitude(values, "gyro").tolist()
        return {
            "recording_id": recording_id,
            "derivative_id": derivative_id,
            "source": signal.source,
            "points": int(len(idx)),
            "total_points": int(len(signal.t_us)),
            "decimated": bool(len(idx) < len(signal.t_us)),
            "t_s": signal.timeline_s[idx].tolist(),
            "channels": channels,
            "duration_s": float(np.nanmax(signal.timeline_s)) if len(signal.timeline_s) else 0.0,
            "fs_hz": signal.fs_hz,
            "uniform": signal.uniform,
            "markers": markers,
            "segments": segments,
            "units": {"accel": "g", "gyro": "deg/s"},
        }

    def update(self, recording_id: str, changes: dict) -> dict:
        with self.db.begin() as db:
            row = self.get_row(db, recording_id)
            if "label_id" in changes:
                label_id = changes["label_id"]
                if label_id is not None and db.get(LabelRow, label_id) is None:
                    raise not_found("Label", label_id)
                old = row.label_id
                row.label_id = label_id
                if old != label_id:
                    self.activity.info("dataset", f"Relabeled {recording_id}: {old} → {label_id}", recording_id=recording_id)
            if "notes" in changes:
                row.notes = changes["notes"] or ""
            if "session_id" in changes:
                row.session_id = changes["session_id"]
            if "kind" in changes:
                if changes["kind"] not in ("trial", "continuous"):
                    raise AppError("invalid_kind", "kind must be 'trial' or 'continuous'", 422)
                row.kind = changes["kind"]
            names = self.label_names(db)
            return self.to_dict(row, names)

    def delete(self, recording_id: str, mode: str) -> dict:
        if mode not in ("metadata", "disk"):
            raise AppError("invalid_mode", "mode must be 'metadata' or 'disk'", 422)
        with self.db.begin() as db:
            row = self.get_row(db, recording_id)
            path = self.path_for(row)
            derivatives = db.scalars(select(DerivativeRow).where(DerivativeRow.recording_id == recording_id)).all()
            removed_files: list[str] = []
            if mode == "disk":
                if not self.app_owned(row):
                    raise conflict("disk_delete_not_allowed", "Only files this app created (data/raw, data/processed) can be deleted from disk. Legacy CLI files and original reference files are never deleted by the app.")
                for d in derivatives:
                    removed_files.extend(self._remove_derivative_files(d))
                for target in (path, path.with_name(path.stem + ".meta.json")):
                    if target.is_file():
                        target.unlink()
                        removed_files.append(str(target))
            for d in derivatives:
                db.delete(d)
            db.query(SegmentRow).filter(SegmentRow.recording_id == recording_id).delete()
            db.query(DatasetMemberRow).filter(DatasetMemberRow.recording_id == recording_id).delete()
            db.delete(row)
        kept = [] if mode == "disk" else [str(path)]
        self.activity.warning("dataset", f"Recording {recording_id} {'deleted from disk' if mode == 'disk' else 'removed from library (file kept)'}", recording_id=recording_id, mode=mode)
        return {"recording_id": recording_id, "mode": mode, "removed_files": removed_files, "kept_files": kept}

    def _remove_derivative_files(self, d: DerivativeRow) -> list[str]:
        removed = []
        path = self.paths.resolve("data", d.file_path)
        for target in (path, path.with_name(path.stem + ".manifest.json")):
            if target.is_file():
                target.unlink()
                removed.append(str(target))
        return removed

    def revalidate(self, recording_id: str) -> dict:
        with self.db.begin() as db:
            row = self.get_row(db, recording_id)
            path = self.path_for(row)
            if not path.is_file():
                raise AppError("file_missing", f"The recording file is missing: {path}", 410)
            digest = sha256_file(path)
            row.source_changed = digest != row.sha256
            table = read_imu_csv(path, time_unit=row.time_unit if row.header_alias == "time" else None)
            report, _ = validate_table(table)
            row.validation = report
            row.validation_state = report["state"]
            names = self.label_names(db)
            return self.to_dict(row, names, include_validation=True)

    def segment_dict(self, s: SegmentRow, names: dict | None = None) -> dict:
        return {
            "segment_id": s.segment_id,
            "recording_id": s.recording_id,
            "label_id": s.label_id,
            "label_name": (names or {}).get(s.label_id),
            "start_s": s.start_s,
            "end_s": s.end_s,
            "duration_s": s.end_s - s.start_s,
            "notes": s.notes,
            "created_at": iso(s.created_at),
        }

    def add_segment(self, recording_id: str, label_id: str, start_s: float, end_s: float, notes: str = "") -> dict:
        if end_s <= start_s:
            raise AppError("invalid_segment", "end_s must be greater than start_s", 422)
        with self.db.begin() as db:
            row = self.get_row(db, recording_id)
            if db.get(LabelRow, label_id) is None:
                raise not_found("Label", label_id)
            limit = (row.duration_s or 0) + 1.0 * max(0, (row.validation or {}).get("timestamps", {}).get("epochs", 1) - 1) + 0.05
            if start_s < -0.001 or end_s > limit + 0.001:
                raise AppError("segment_out_of_range", f"Segment must lie within 0–{limit:.2f} s of the recording timeline", 422)
            segment = SegmentRow(segment_id=new_id("seg", label_id), recording_id=recording_id, label_id=label_id, start_s=float(start_s), end_s=float(end_s), notes=notes or "")
            db.add(segment)
            db.flush()
            return self.segment_dict(segment, self.label_names(db))

    def update_segment(self, segment_id: str, changes: dict) -> dict:
        with self.db.begin() as db:
            s = db.get(SegmentRow, segment_id)
            if s is None:
                raise not_found("Segment", segment_id)
            self.get_row(db, s.recording_id)
            for key in ("label_id", "start_s", "end_s", "notes"):
                if key in changes and changes[key] is not None:
                    setattr(s, key, changes[key])
            if s.end_s <= s.start_s:
                raise AppError("invalid_segment", "end_s must be greater than start_s", 422)
            if db.get(LabelRow, s.label_id) is None:
                raise not_found("Label", s.label_id)
            return self.segment_dict(s, self.label_names(db))

    def delete_segment(self, segment_id: str) -> None:
        with self.db.begin() as db:
            s = db.get(SegmentRow, segment_id)
            if s is None:
                raise not_found("Segment", segment_id)
            self.get_row(db, s.recording_id)
            db.query(DatasetMemberRow).filter(DatasetMemberRow.segment_id == segment_id).delete()
            db.delete(s)

    def derivative_dict(self, d: DerivativeRow) -> dict:
        return {
            "derivative_id": d.derivative_id,
            "recording_id": d.recording_id,
            "recipe_name": d.recipe_name,
            "recipe": d.recipe,
            "file_path": d.file_path,
            "sha256": d.sha256,
            "sample_count": d.sample_count,
            "fs_hz": d.fs_hz,
            "uniform": d.uniform,
            "step_counts": d.step_counts,
            "created_at": iso(d.created_at),
        }

    def create_derivative(self, recording_id: str, recipe: RepairRecipe) -> dict:
        with self.db() as db:
            row = self.get_row(db, recording_id)
        table = self.read_table(row)
        result = apply_recipe(table, recipe)
        if result.n < 2:
            raise conflict("repair_left_no_data", "The recipe removed every usable sample", {"step_counts": result.step_counts})
        workspace = self.workspace()
        derivative_id = new_id("der", recipe.name)
        out_dir = self.paths.processed_dir(workspace)
        path = out_dir / f"{derivative_id}.csv"
        write_derivative_csv(path, result.t_us, result.values, result.epoch, result.segment)
        digest = sha256_file(path)
        manifest = {
            "derivative_id": derivative_id,
            "pipeline": recipe.version,
            "source": {"recording_id": recording_id, "sha256": row.sha256, "file": {"base": row.storage_base, "path": row.file_path}},
            "recipe": recipe.model_dump(),
            "step_counts": result.step_counts,
            "output": {"rows": result.n, "fs_hz": result.fs_hz, "uniform": result.uniform, "segments": len(result.segments()), "sha256": digest},
            "app": APP_VERSION_TAG,
        }
        write_json(path.with_name(f"{derivative_id}.manifest.json"), manifest, exclusive=True)
        relative = self.paths.relative_to_base("data", path)
        with self.db.begin() as db:
            d = DerivativeRow(
                derivative_id=derivative_id,
                recording_id=recording_id,
                workspace=workspace,
                recipe_name=recipe.name,
                recipe=recipe.model_dump(),
                file_path=relative,
                sha256=digest,
                sample_count=result.n,
                fs_hz=result.fs_hz,
                uniform=result.uniform,
                step_counts=result.step_counts,
            )
            db.add(d)
            db.flush()
            out = self.derivative_dict(d)
        self.activity.info("dataset", f"Created derivative {derivative_id} from {recording_id} with recipe {recipe.name}", recording_id=recording_id)
        return out

    def delete_derivative(self, derivative_id: str) -> dict:
        with self.db.begin() as db:
            d = db.get(DerivativeRow, derivative_id)
            if d is None or d.workspace != self.workspace():
                raise not_found("Derivative", derivative_id)
            removed = self._remove_derivative_files(d)
            db.query(DatasetMemberRow).filter(DatasetMemberRow.derivative_id == derivative_id).update({DatasetMemberRow.derivative_id: None})
            db.delete(d)
        return {"derivative_id": derivative_id, "removed_files": removed}

    def recover_orphans(self) -> dict:
        workspace = self.workspace()
        root = self.paths.raw_root(workspace)
        recovered, skipped = [], []
        with self.db() as db:
            known = set(db.scalars(select(RecordingRow.recording_id)).all())
        for meta_path in root.rglob("*.meta.json"):
            if "_staging" in meta_path.parts or (workspace == "real" and "demo" in meta_path.relative_to(root).parts[:1]):
                continue
            try:
                meta = read_json(meta_path)
            except (OSError, ValueError):
                skipped.append({"file": str(meta_path), "reason": "unreadable"})
                continue
            rid = meta.get("recording_id")
            if not rid or rid in known:
                continue
            csv_path = meta_path.with_name(meta_path.name.replace(".meta.json", ".csv"))
            if not csv_path.is_file():
                skipped.append({"file": str(meta_path), "reason": "csv missing"})
                continue
            recovered.append(self.register_from_file(csv_path, meta))
        return {"recovered": recovered, "skipped": skipped}

    def register_from_file(self, csv_path: Path, meta: dict, storage_base: str = "data") -> str:
        table = read_imu_csv(csv_path, time_unit=meta.get("time_unit") if meta.get("header_alias") == "time" else None)
        report, analysis = validate_table(table)
        from datetime import datetime

        start = meta.get("start_time")
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")).replace(tzinfo=None) if start else None
        with self.db.begin() as db:
            label_id = meta.get("label_id")
            if label_id and db.get(LabelRow, label_id) is None:
                label_id = None
            session_id = meta.get("session_id")
            if session_id and db.get(SessionRow, session_id) is None:
                session_id = None
            row = RecordingRow(
                recording_id=meta["recording_id"],
                workspace=meta.get("workspace", self.workspace()),
                kind=meta.get("kind", "trial"),
                source=meta.get("source", "live"),
                label_id=label_id,
                sensor_id=meta.get("sensor_id"),
                sensor_hand=meta.get("sensor_hand", "unassigned"),
                session_id=session_id,
                capture_id=meta.get("capture_id"),
                start_time=start_dt,
                device_t0_us=meta.get("device_t0_us"),
                duration_s=report["duration_s"],
                sample_count=table.rows_total,
                fs_median_hz=report["rates"]["fs_median_hz"],
                fs_mean_hz=report["rates"]["fs_mean_hz"],
                storage_base=storage_base,
                file_path=self.paths.relative_to_base(storage_base, csv_path),
                sha256=sha256_file(csv_path),
                size_bytes=csv_path.stat().st_size,
                header_alias=table.header_alias,
                time_unit=table.time_unit,
                firmware_header=meta.get("firmware_header"),
                validation_state=report["state"],
                validation=report,
                notes=meta.get("notes", ""),
                provenance={**(meta.get("provenance") or {}), "recovered_from_meta": True},
            )
            db.add(row)
        return meta["recording_id"]
