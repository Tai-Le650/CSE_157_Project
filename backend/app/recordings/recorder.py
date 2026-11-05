from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ..api.errors import AppError, conflict, not_found
from ..processing.csv_io import AXES, magnitude, read_imu_csv
from ..processing.timeline import timeline_seconds
from ..processing.timestamps import classify_timestamps
from ..processing.validation import validate_table
from .library import APP_VERSION_TAG, decimate
from .storage import dated_dir, move_no_overwrite, new_id, read_json, write_json, write_legacy_csv, write_samples_csv

DEMO_REACTION_S = 0.35


@dataclass
class TrialConfig:
    label_id: str
    sensor_ids: list[str]
    duration_s: float
    countdown_s: float
    trials: int
    pause_s: float
    session_id: str
    notes: str


class RecorderService:
    snapshot_key = "recorder"

    def __init__(self, paths: Any, bus: Any, sensors: Any, hub: Any, activity: Any, library: Any, labels: Any, sessions: Any, workspace_provider):
        self.paths = paths
        self.bus = bus
        self.sensors = sensors
        self.hub = hub
        self.activity = activity
        self.library = library
        self.labels = labels
        self.sessions = sessions
        self.workspace = workspace_provider
        self._lock = threading.RLock()
        self._capture: dict[str, list] | None = None
        self._window: tuple[int, int | None] = (0, None)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._staging: dict[str, dict] = {}
        self._continuous: dict | None = None
        self.current_session_id: str | None = None
        self.state = self._idle_state()
        bus.subscribe("recorder", self._on_samples)
        sensors.add_listener(self._on_sensor_event)

    def _idle_state(self, message: str = "") -> dict:
        return {"active": False, "mode": None, "phase": "idle", "label_id": None, "sensor_ids": [], "trial": 0, "trials": 0, "countdown_remaining_s": None, "elapsed_s": None, "duration_s": None, "message": message, "session_id": self.current_session_id if hasattr(self, "current_session_id") else None, "capture_id": None}

    @property
    def active(self) -> bool:
        return bool(self.state.get("active"))

    def snapshot(self) -> dict:
        return {"state": dict(self.state), "staging": self.list_staging()}

    def publish(self) -> None:
        self.hub.publish("recorder", "recorder", self.snapshot())

    def _set(self, **changes) -> None:
        self.state.update(changes)
        self.publish()

    def on_startup(self) -> None:
        for workspace in ("real", "demo"):
            staging = self.paths.staging_dir(workspace)
            if not staging.is_dir():
                continue
            for meta_path in staging.glob("*.meta.json"):
                try:
                    meta = read_json(meta_path)
                except (OSError, ValueError):
                    continue
                meta["_meta_path"] = str(meta_path)
                self._staging[meta["recording_id"]] = meta

    def on_shutdown(self) -> None:
        self.abort("shutdown")

    def _on_samples(self, sensor_id: str, samples: list) -> None:
        capture = self._capture
        if capture is None or sensor_id not in capture:
            return
        start, end = self._window
        with self._lock:
            target = capture.get(sensor_id)
            if target is None:
                return
            for s in samples:
                if s.host_ns < start or (end is not None and s.host_ns > end):
                    continue
                target.append(s)

    def _on_sensor_event(self, event: str, sensor_id: str, _data: dict) -> None:
        if not self.active or event not in ("lost", "stalled", "disconnected"):
            return
        if sensor_id in self.state.get("sensor_ids", []):
            self.abort(f"sensor {sensor_id} {event}")

    def _check_sensors(self, sensor_ids: list[str]) -> None:
        if not sensor_ids:
            raise AppError("no_sensors", "Select at least one streaming sensor", 422)
        for sid in sensor_ids:
            session = self.sensors.get(sid)
            if session.status != "streaming":
                raise conflict("sensor_not_streaming", f"Sensor {sid} is {session.status}; it must be streaming to record")

    def _resolve_session(self, session_id: str | None) -> str:
        if session_id:
            self.sessions.ensure_exists(session_id)
            self.current_session_id = session_id
            return session_id
        if self.current_session_id:
            try:
                self.sessions.ensure_exists(self.current_session_id)
                return self.current_session_id
            except AppError:
                pass
        created = self.sessions.create(f"Session {datetime.now():%Y-%m-%d %H:%M}", source="demo" if self.workspace() == "demo" else "live")
        self.current_session_id = created["session_id"]
        return self.current_session_id

    def new_session(self, name: str, notes: str = "") -> dict:
        created = self.sessions.create(name or f"Session {datetime.now():%Y-%m-%d %H:%M}", notes, source="demo" if self.workspace() == "demo" else "live")
        self.current_session_id = created["session_id"]
        self.publish()
        return created

    def start_trials(self, label_id: str, sensor_ids: list[str], duration_s: float, countdown_s: float, trials: int, pause_s: float, session_id: str | None, notes: str = "") -> dict:
        with self._lock:
            if self.active:
                raise conflict("recorder_busy", "A recording is already in progress")
            if label_id not in self.labels.enabled_ids():
                raise conflict("label_not_enabled", f"Label '{label_id}' does not exist or is disabled")
            self._check_sensors(sensor_ids)
            session = self._resolve_session(session_id)
            config = TrialConfig(label_id, list(dict.fromkeys(sensor_ids)), duration_s, countdown_s, trials, pause_s, session, notes)
            self._stop.clear()
            self.state = {**self._idle_state(), "active": True, "mode": "trials", "phase": "starting", "label_id": label_id, "sensor_ids": config.sensor_ids, "trial": 0, "trials": trials, "duration_s": duration_s, "session_id": session}
            self._thread = threading.Thread(target=self._run_trials, args=(config,), name="recorder", daemon=True)
            self._thread.start()
        self.activity.info("recorder", f"Recording {trials} × {label_id} trial(s) on {', '.join(config.sensor_ids)}", session_id=session)
        self.publish()
        return self.snapshot()

    def _sleep(self, seconds: float) -> bool:
        return not self._stop.wait(max(0.0, seconds))

    def _run_trials(self, config: TrialConfig) -> None:
        message = "Finished"
        try:
            for index in range(config.trials):
                if self._stop.is_set():
                    break
                deadline = time.monotonic() + config.countdown_s
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self._set(phase="countdown", trial=index + 1, countdown_remaining_s=round(remaining, 1), message=f"Trial {index + 1}/{config.trials}: get ready")
                    if not self._sleep(min(0.25, remaining)):
                        break
                if self._stop.is_set():
                    break
                capture_id = new_id("cap", config.label_id)
                started_wall = datetime.now(timezone.utc)
                start_ns = time.perf_counter_ns()
                with self._lock:
                    self._window = (start_ns, None)
                    self._capture = {sid: [] for sid in config.sensor_ids}
                self._set(phase="recording", countdown_remaining_s=0, capture_id=capture_id, elapsed_s=0.0, message="GO — perform the gesture now" if config.label_id not in self.labels.idle_ids() else "Hold still (idle)")
                self._trigger_demo(config.sensor_ids, config.label_id)
                end_at = time.monotonic() + config.duration_s
                while time.monotonic() < end_at and not self._stop.is_set():
                    self._sleep(min(0.1, end_at - time.monotonic()))
                    self.state["elapsed_s"] = round(config.duration_s - max(0.0, end_at - time.monotonic()), 2)
                end_ns = start_ns + int(config.duration_s * 1e9)
                with self._lock:
                    self._window = (start_ns, end_ns)
                if self._stop.is_set():
                    with self._lock:
                        self._capture = None
                    message = "Stopped; the unfinished trial was discarded"
                    break
                time.sleep(0.12)
                with self._lock:
                    captured = self._capture or {}
                    self._capture = None
                self._set(phase="saving", message="Checking trial")
                for sid, samples in captured.items():
                    self._write_staging(sid, samples, config.label_id, config.session_id, capture_id, "trial", started_wall, config.notes, {"trial_index": index + 1, "trials": config.trials, "duration_s": config.duration_s, "countdown_s": config.countdown_s})
                if index + 1 < config.trials and config.pause_s > 0:
                    self._set(phase="pause", message="Return to the starting pose")
                    if not self._sleep(config.pause_s):
                        break
            if self._stop.is_set() and message == "Finished":
                message = "Stopped"
        except Exception as exc:
            message = f"Recorder error: {exc}"
            self.activity.error("recorder", message)
        finally:
            with self._lock:
                self._capture = None
                self.state = self._idle_state(message)
            self.publish()

    def _trigger_demo(self, sensor_ids: list[str], label_id: str) -> None:
        demos = [s.demo for s in (self.sensors.sessions.get(sid) for sid in sensor_ids) if s is not None and s.demo is not None and label_id in s.demo.gestures]
        if not demos:
            return
        timer = threading.Timer(DEMO_REACTION_S, lambda: [demo.perform(label_id) for demo in demos])
        timer.daemon = True
        timer.start()

    def start_continuous(self, label_id: str | None, sensor_ids: list[str], session_id: str | None, notes: str = "") -> dict:
        with self._lock:
            if self.active:
                raise conflict("recorder_busy", "A recording is already in progress")
            if label_id is not None and not self.labels.exists(label_id):
                raise not_found("Label", label_id)
            self._check_sensors(sensor_ids)
            session = self._resolve_session(session_id)
            capture_id = new_id("cap", "continuous")
            self._continuous = {"label_id": label_id, "sensor_ids": list(dict.fromkeys(sensor_ids)), "session_id": session, "notes": notes, "capture_id": capture_id, "started_wall": datetime.now(timezone.utc), "started": time.monotonic()}
            self._window = (time.perf_counter_ns(), None)
            self._capture = {sid: [] for sid in self._continuous["sensor_ids"]}
            self._stop.clear()
            self.state = {**self._idle_state(), "active": True, "mode": "continuous", "phase": "recording", "label_id": label_id, "sensor_ids": self._continuous["sensor_ids"], "session_id": session, "capture_id": capture_id, "message": "Recording continuously — mix idle and gestures, then label segments later"}
        self.activity.info("recorder", f"Continuous recording started on {', '.join(sensor_ids)}")
        self.publish()
        return self.snapshot()

    def stop_recording(self) -> dict:
        if not self.active:
            return self.snapshot()
        if self.state.get("mode") == "continuous" and self._continuous is not None:
            info = self._continuous
            with self._lock:
                self._window = (self._window[0], time.perf_counter_ns())
            time.sleep(0.12)
            with self._lock:
                captured = self._capture or {}
                self._capture = None
                self._continuous = None
            for sid, samples in captured.items():
                self._write_staging(sid, samples, info["label_id"], info["session_id"], info["capture_id"], "continuous", info["started_wall"], info["notes"], {"duration_s": round(time.monotonic() - info["started"], 3)})
            self.state = self._idle_state("Continuous recording stopped; review it in staging")
            self.publish()
            return self.snapshot()
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        return self.snapshot()

    def abort(self, reason: str) -> None:
        if not self.active:
            return
        self._stop.set()
        with self._lock:
            self._capture = None
            self._continuous = None
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)
        self.state = self._idle_state(f"Recording aborted: {reason}")
        self.activity.warning("recorder", f"Recording aborted ({reason}); unfinished data discarded")
        self.publish()

    def _write_staging(self, sensor_id: str, samples: list, label_id: str | None, session_id: str, capture_id: str, kind: str, started_wall: datetime, notes: str, recorder_info: dict) -> dict:
        workspace = self.workspace()
        session = self.sensors.sessions.get(sensor_id)
        recording_id = new_id("rec", label_id or "unlabeled", sensor_id)
        staging = self.paths.staging_dir(workspace)
        csv_path = staging / f"{recording_id}.csv"
        count = write_samples_csv(csv_path, samples)
        table = read_imu_csv(csv_path)
        report, _analysis = validate_table(table)
        reader = session.reader if session else None
        meta = {
            "recording_id": recording_id,
            "workspace": workspace,
            "kind": kind,
            "source": "demo" if (session and session.simulated) else "live",
            "label_id": label_id,
            "sensor_id": sensor_id,
            "sensor_hand": session.hand if session else "unassigned",
            "session_id": session_id,
            "capture_id": capture_id,
            "start_time": started_wall.isoformat().replace("+00:00", "Z"),
            "device_t0_us": int(samples[0].t_raw) if samples else None,
            "duration_s": report["duration_s"],
            "sample_count": count,
            "fs_median_hz": report["rates"]["fs_median_hz"],
            "fs_mean_hz": report["rates"]["fs_mean_hz"],
            "header_alias": "t_us",
            "time_unit": "us",
            "units": {"accel": "g", "gyro": "deg/s", "time": "us (device micros, raw)", "host_rx_ns": "host perf_counter ns at line receipt"},
            "firmware_header": session.header_alias if session else None,
            "column_order_assumed": (session.header_alias is None) if session else True,
            "notes": notes,
            "validation_state": report["state"],
            "validation": report,
            "provenance": {
                "origin": "demo_simulator" if (session and session.simulated) else "live_serial",
                "simulated": bool(session and session.simulated),
                "port": session.port if session else None,
                "baud": session.baud if session else None,
                "recorder": recorder_info,
                "stream_counters": reader.counters.as_dict() if reader else None,
                "app": APP_VERSION_TAG,
            },
        }
        meta_path = staging / f"{recording_id}.meta.json"
        write_json(meta_path, meta, exclusive=True)
        meta["_meta_path"] = str(meta_path)
        with self._lock:
            self._staging[recording_id] = meta
        if report["state"] != "valid":
            self.activity.warning("recorder", f"Trial {recording_id} is {report['state']}: " + "; ".join(i["message"] for i in report["issues"] if i["severity"] != "info"))
        self.publish()
        return self._summary(meta)

    def _summary(self, meta: dict) -> dict:
        return {
            "staging_id": meta["recording_id"],
            "recording_id": meta["recording_id"],
            "kind": meta["kind"],
            "source": meta["source"],
            "label_id": meta["label_id"],
            "sensor_id": meta["sensor_id"],
            "session_id": meta["session_id"],
            "capture_id": meta.get("capture_id"),
            "start_time": meta["start_time"],
            "duration_s": meta["duration_s"],
            "sample_count": meta["sample_count"],
            "fs_median_hz": meta["fs_median_hz"],
            "validation_state": meta["validation_state"],
            "issues": [i for i in meta["validation"]["issues"] if i["severity"] != "info"],
            "notes": meta.get("notes", ""),
            "workspace": meta["workspace"],
        }

    def list_staging(self) -> list[dict]:
        workspace = self.workspace()
        with self._lock:
            items = [self._summary(m) for m in self._staging.values() if m.get("workspace") == workspace]
        return sorted(items, key=lambda m: m["start_time"])

    def _staged(self, staging_id: str) -> dict:
        meta = self._staging.get(staging_id)
        if meta is None or meta.get("workspace") != self.workspace():
            raise not_found("Staged recording", staging_id)
        return meta

    def staging_csv_path(self, staging_id: str) -> Path:
        meta = self._staged(staging_id)
        return Path(meta["_meta_path"]).with_name(f"{staging_id}.csv")

    def preview(self, staging_id: str, max_points: int = 2000) -> dict:
        path = self.staging_csv_path(staging_id)
        table = read_imu_csv(path)
        analysis = classify_timestamps(table.t_us, valid=table.valid_rows)
        good = analysis.good_mask & table.valid_rows
        t = analysis.t_us[good]
        epoch = analysis.epoch[good].astype(np.int64)
        timeline = timeline_seconds(t, epoch)
        idx = decimate(len(t), max_points)
        values = table.values[good][idx]
        channels = {axis: values[:, i].tolist() for i, axis in enumerate(AXES)}
        channels["amag"] = magnitude(values, "accel").tolist()
        channels["gmag"] = magnitude(values, "gyro").tolist()
        return {
            "staging_id": staging_id,
            "t_s": timeline[idx].tolist(),
            "channels": channels,
            "points": int(len(idx)),
            "total_points": int(len(t)),
            "decimated": bool(len(idx) < len(t)),
            "duration_s": float(np.nanmax(timeline)) if len(timeline) else 0.0,
            "fs_hz": analysis.fs_median_hz(),
            "uniform": False,
            "markers": [],
            "segments": [],
            "units": {"accel": "g", "gyro": "deg/s"},
        }

    def update_staging(self, staging_id: str, notes: str | None = None, label_id: str | None = None) -> dict:
        meta = self._staged(staging_id)
        if label_id is not None:
            if not self.labels.exists(label_id):
                raise not_found("Label", label_id)
            meta["label_id"] = label_id
        if notes is not None:
            meta["notes"] = notes
        clean = {k: v for k, v in meta.items() if not k.startswith("_")}
        write_json(Path(meta["_meta_path"]), clean)
        self.publish()
        return self._summary(meta)

    def save(self, staging_ids: list[str]) -> dict:
        saved, errors = [], []
        workspace = self.workspace()
        for staging_id in staging_ids:
            try:
                meta = self._staged(staging_id)
                csv_path = Path(meta["_meta_path"]).with_name(f"{staging_id}.csv")
                started = datetime.fromisoformat(meta["start_time"].replace("Z", "+00:00"))
                target_dir = dated_dir(self.paths.raw_root(workspace), started)
                final_csv = move_no_overwrite(csv_path, target_dir, csv_path.name)
                clean = {k: v for k, v in meta.items() if not k.startswith("_")}
                clean["file"] = final_csv.name
                meta_target = target_dir / f"{staging_id}.meta.json"
                write_json(meta_target, clean, exclusive=True)
                Path(meta["_meta_path"]).unlink(missing_ok=True)
                self.library.register_from_file(final_csv, clean)
                with self._lock:
                    self._staging.pop(staging_id, None)
                saved.append(staging_id)
            except Exception as exc:
                errors.append({"staging_id": staging_id, "error": str(exc)})
        if saved:
            self.activity.info("recorder", f"Saved {len(saved)} recording(s) to data/raw", count=len(saved))
        self.publish()
        return {"saved": saved, "errors": errors}

    def discard(self, staging_ids: list[str], confirm: bool) -> dict:
        if not confirm:
            raise conflict("confirmation_required", "Discarding deletes the staged files permanently. Resend with confirm=true.")
        removed = []
        for staging_id in staging_ids:
            meta = self._staged(staging_id)
            meta_path = Path(meta["_meta_path"])
            meta_path.with_name(f"{staging_id}.csv").unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            with self._lock:
                self._staging.pop(staging_id, None)
            removed.append(staging_id)
        if removed:
            self.activity.info("recorder", f"Discarded {len(removed)} staged trial(s)")
        self.publish()
        return {"discarded": removed}

    def export_legacy_csv(self, staging_id: str) -> tuple[str, str]:
        path = self.staging_csv_path(staging_id)
        table = read_imu_csv(path)
        rows = [(int(table.t_raw[i]), *table.values[i]) for i in range(table.n) if table.valid_rows[i]]
        return f"{staging_id}.csv", write_legacy_csv(rows)
