from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..api.errors import AppError, conflict
from ..database.models import RecordingRow
from ..processing.csv_io import read_imu_csv
from ..processing.validation import validate_table
from .library import APP_VERSION_TAG
from .storage import copy_no_overwrite, new_id, safe_token, sha256_bytes, sha256_file, write_bytes_no_overwrite, write_json

IMPORTER_VERSION = "importer-v1"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

KNOWN_SOURCES = {
    "imu_capture/swipe_left": {
        "relative": "imu_capture/recordings/swipe_left.csv",
        "label_id": "swipe_left",
        "description": "≈12 s recording with about two swipe-left movements separated by idle periods",
    },
    "imu_capture/swipe_right": {
        "relative": "imu_capture/recordings/swipe_right.csv",
        "label_id": "swipe_right",
        "description": "≈12 s recording with about two swipe-right movements separated by idle periods",
    },
    "imu_capture/wrist_rotation": {
        "relative": "imu_capture/recordings/wrist_rotation.csv",
        "label_id": "wrist_rotation",
        "description": "≈12 s recording with wrist-rotation (twist) movements separated by idle periods",
    },
}
DOCUMENTED_FIRMWARE = "Header time_us matches imu_capture/imu_capture.ino, whose source code configures ±4 g and ±500 dps. This is documented in source code, not measured."


class ImportService:
    def __init__(self, paths: Any, db: Any, library: Any, labels: Any, sessions: Any, activity: Any, workspace_provider):
        self.paths = paths
        self.db = db
        self.library = library
        self.labels = labels
        self.sessions = sessions
        self.activity = activity
        self.workspace = workspace_provider

    def _require_real(self) -> None:
        if self.workspace() != "real":
            raise conflict("imports_need_real_mode", "Imports bring real recordings into the library; switch Demo Mode off first")

    def _imported_hashes(self) -> dict[str, str]:
        with self.db() as db:
            rows = db.scalars(select(RecordingRow).where(RecordingRow.workspace == "real", RecordingRow.source == "import")).all()
            return {(r.provenance or {}).get("source_sha256"): r.recording_id for r in rows if (r.provenance or {}).get("source_sha256")}

    def known_sources(self) -> list[dict]:
        imported = self._imported_hashes()
        out = []
        for key, info in KNOWN_SOURCES.items():
            path = self.paths.reference_root / info["relative"]
            exists = path.is_file()
            digest = sha256_file(path) if exists else None
            out.append({
                "key": key,
                "path": info["relative"],
                "absolute": str(path),
                "exists": exists,
                "size_bytes": path.stat().st_size if exists else None,
                "sha256": digest,
                "label_hint": info["label_id"],
                "kind": "continuous",
                "description": info["description"],
                "imported_recording_id": imported.get(digest) if digest else None,
            })
        return out

    def _register_copy(self, data: bytes, original_name: str, folder: str, kind: str, label_id: str | None, time_unit: str | None, session_id: str | None, notes: str, provenance: dict) -> dict:
        table = read_imu_csv(data, time_unit=time_unit)
        report, _ = validate_table(table)
        recording_id = new_id("imp", label_id or "unlabeled")
        target_dir = self.paths.imports_dir("real") / folder
        name = f"{recording_id}__{safe_token(Path(original_name).stem, 'file', 60)}.csv"
        csv_path = write_bytes_no_overwrite(data, target_dir, name)
        copied = sha256_file(csv_path)
        if copied != provenance.get("source_sha256"):
            csv_path.unlink(missing_ok=True)
            raise AppError("copy_verification_failed", "The imported copy does not match the source bytes", 500)
        meta = {
            "recording_id": recording_id,
            "workspace": "real",
            "kind": kind,
            "source": "import",
            "label_id": label_id,
            "sensor_id": None,
            "sensor_hand": "unassigned",
            "session_id": session_id,
            "capture_id": None,
            "start_time": None,
            "device_t0_us": int(table.t_us[table.valid_rows][0]) if table.valid_rows.any() and table.time_unit == "us" else None,
            "header_alias": table.header_alias,
            "time_unit": table.time_unit,
            "firmware_header": table.header_alias if table.header_alias in ("t_us", "time_us") else None,
            "notes": notes,
            "validation_state": report["state"],
            "validation": report,
            "provenance": {**provenance, "copied_sha256": copied, "importer": IMPORTER_VERSION, "imported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "app": APP_VERSION_TAG, "start_time_note": "The original recording start time is unknown; see file_modified_time for the source file's filesystem timestamp."},
        }
        write_json(csv_path.with_name(csv_path.name[:-4] + ".meta.json"), meta, exclusive=True)
        self.library.register_from_file(csv_path, meta)
        return {"recording_id": recording_id, "validation_state": report["state"], "issues": [i for i in report["issues"] if i["severity"] != "info"], "file": str(csv_path)}

    def import_known(self, keys: list[str], session_mode: str = "batch", session_name: str | None = None) -> dict:
        self._require_real()
        unknown = [k for k in keys if k not in KNOWN_SOURCES]
        if unknown:
            raise AppError("unknown_source", f"Unknown import source(s): {', '.join(unknown)}", 422, {"known": list(KNOWN_SOURCES)})
        if session_mode not in ("batch", "per_file", "none"):
            raise AppError("invalid_session_mode", "session_mode must be batch, per_file or none", 422)
        imported_hashes = self._imported_hashes()
        batch_session = None
        if session_mode == "batch":
            batch_session = self.sessions.create(session_name or "imu_capture import (one mounting session assumed)", "Created on import; edit if the files came from different sessions.", source="import")["session_id"]
        results, skipped = [], []
        for key in keys:
            info = KNOWN_SOURCES[key]
            path = self.paths.reference_root / info["relative"]
            if not path.is_file():
                skipped.append({"key": key, "reason": f"source file not found: {path}"})
                continue
            data = path.read_bytes()
            digest = sha256_bytes(data)
            if digest in imported_hashes:
                skipped.append({"key": key, "reason": "already imported", "recording_id": imported_hashes[digest]})
                continue
            session_id = batch_session
            if session_mode == "per_file":
                session_id = self.sessions.create(f"{key} import", source="import")["session_id"]
            provenance = {
                "origin": "known_source",
                "key": key,
                "source_path": info["relative"],
                "source_root": "project folder (sibling of XIAO_Gesture_Controller)",
                "source_sha256": digest,
                "file_modified_time": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
                "documented_firmware": DOCUMENTED_FIRMWARE,
                "label_basis": "Label hint from the source file name; segments must be annotated before training.",
            }
            results.append(self._register_copy(data, path.name, "imu_capture", "continuous", info["label_id"], None, session_id, info["description"], provenance))
        if results:
            self.activity.info("dataset", f"Imported {len(results)} reference recording(s) from imu_capture (originals untouched)")
        return {"imported": results, "skipped": skipped}

    def import_upload(self, filename: str, data: bytes, kind: str, label_id: str | None, time_unit: str | None, session_id: str | None, notes: str) -> dict:
        self._require_real()
        if len(data) > MAX_UPLOAD_BYTES:
            raise AppError("file_too_large", f"Uploads are limited to {MAX_UPLOAD_BYTES // (1024 * 1024)} MB", 413)
        if kind not in ("trial", "continuous"):
            raise AppError("invalid_kind", "kind must be 'trial' or 'continuous'", 422)
        if label_id is not None and not self.labels.exists(label_id):
            raise AppError("unknown_label", f"Label '{label_id}' does not exist", 422)
        self.sessions.ensure_exists(session_id)
        digest = sha256_bytes(data)
        provenance = {"origin": "upload", "original_filename": filename, "source_sha256": digest, "time_unit_supplied": time_unit}
        result = self._register_copy(data, filename, "uploads", kind, label_id, time_unit, session_id, notes, provenance)
        self.activity.info("dataset", f"Imported upload {filename}", recording_id=result["recording_id"])
        return result

    def rescan_legacy(self) -> dict:
        self._require_real()
        folder = self.paths.cli_data_dir
        registered, unchanged, changed, skipped = [], [], [], []
        if not folder.is_dir():
            return {"folder": str(folder), "registered": registered, "unchanged": unchanged, "changed": changed, "skipped": skipped}
        with self.db() as db:
            existing = {r.file_path: r for r in db.scalars(select(RecordingRow).where(RecordingRow.storage_base == "cli_data")).all()}
        for path in sorted(folder.glob("*.csv")):
            if "_" not in path.stem:
                skipped.append({"file": path.name, "reason": "name is not <label>_<number>.csv"})
                continue
            label_id, number = path.stem.rsplit("_", 1)
            if not number.isdigit():
                skipped.append({"file": path.name, "reason": "name is not <label>_<number>.csv"})
                continue
            digest = sha256_file(path)
            row = existing.get(path.name)
            if row is not None:
                if row.sha256 != digest:
                    with self.db.begin() as db:
                        live = db.get(RecordingRow, row.recording_id)
                        live.source_changed = True
                    self.library.revalidate(row.recording_id)
                    changed.append(path.name)
                else:
                    unchanged.append(path.name)
                continue
            try:
                self.labels.ensure_legacy(label_id)
                meta = {
                    "recording_id": new_id("cli", label_id, number),
                    "workspace": "real",
                    "kind": "trial",
                    "source": "legacy_cli",
                    "label_id": label_id,
                    "sensor_id": None,
                    "sensor_hand": "unassigned",
                    "session_id": None,
                    "start_time": None,
                    "notes": "",
                    "provenance": {
                        "origin": "legacy_cli",
                        "file": path.name,
                        "source_sha256": digest,
                        "note": "Recorded by src/collect.py as one 0.9 s trial (per its source code). Session unknown; evaluation groups these by recording.",
                        "file_modified_time": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
                    },
                }
                self.library.register_from_file(path, meta, storage_base="cli_data")
                registered.append(path.name)
            except AppError as exc:
                skipped.append({"file": path.name, "reason": exc.message})
        if registered or changed:
            self.activity.info("dataset", f"Legacy CLI scan: {len(registered)} new, {len(changed)} changed, {len(unchanged)} unchanged")
        return {"folder": str(folder), "registered": registered, "unchanged": unchanged, "changed": changed, "skipped": skipped}
