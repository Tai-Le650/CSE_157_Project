from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

import numpy as np
from sqlalchemy import select

from ..api.errors import AppError, conflict
from ..database.models import SyncMeasurementRow, iso
from ..recordings.storage import new_id

COMBINED_MAX_ERROR_MS = 20.0
PAIR_WINDOW_MS = 150.0
MIN_EVENT_SPACING_S = 0.3


class ClockAlignment:
    def __init__(self, horizon_s: float = 120.0, bin_s: float = 1.0):
        self.horizon_s = horizon_s
        self.bin_s = bin_s
        self.points: deque[tuple[int, float, float]] = deque()
        self.lock = threading.Lock()
        self.epoch: int | None = None

    def add(self, samples: list) -> None:
        with self.lock:
            for s in samples:
                if not s.good or s.t_us is None:
                    continue
                if self.epoch != s.epoch:
                    self.points.clear()
                    self.epoch = s.epoch
                host_us = s.host_ns / 1000.0
                offset = host_us - s.t_us
                bucket = int(host_us / 1e6 / self.bin_s)
                if self.points and self.points[-1][0] == bucket:
                    if offset < self.points[-1][1]:
                        self.points[-1] = (bucket, offset, s.t_us)
                else:
                    self.points.append((bucket, offset, s.t_us))
                while self.points and bucket - self.points[0][0] > self.horizon_s / self.bin_s:
                    self.points.popleft()

    def fit(self) -> dict:
        with self.lock:
            points = list(self.points)
        if len(points) < 3:
            return {"ready": False, "points": len(points)}
        device = np.array([p[2] for p in points])
        offset = np.array([p[1] for p in points])
        ref = device[0]
        slope, intercept = np.polyfit(device - ref, offset, 1)
        residual = offset - (intercept + slope * (device - ref))
        return {"ready": True, "points": len(points), "reference_device_us": float(ref), "offset_us": float(intercept), "drift_ppm": float(slope * 1e6), "envelope_residual_us": float(np.std(residual))}

    def device_to_host_us(self, t_us: np.ndarray) -> np.ndarray:
        model = self.fit()
        if not model["ready"]:
            raise conflict("alignment_not_ready", "Not enough data to align this sensor's clock yet (needs ~3 s of streaming)")
        return t_us + model["offset_us"] + (model["drift_ppm"] / 1e6) * (t_us - model["reference_device_us"])


def detect_impulses(t_us: np.ndarray, values: np.ndarray, threshold_g: float = 0.6) -> list[float]:
    if len(t_us) < 10:
        return []
    accel = np.sqrt(np.sum(values[:, 0:3] ** 2, axis=1))
    baseline = np.median(accel)
    deviation = np.abs(accel - baseline)
    mad = np.median(np.abs(accel - baseline)) + 1e-6
    level = max(threshold_g, 8 * mad)
    events: list[float] = []
    last = -1e18
    candidates = np.flatnonzero(deviation > level)
    for i in candidates:
        if t_us[i] - last < MIN_EVENT_SPACING_S * 1e6:
            if events and deviation[i] > deviation[np.searchsorted(t_us, events[-1])]:
                events[-1] = float(t_us[i])
            continue
        events.append(float(t_us[i]))
        last = t_us[i]
    return events


class SyncService:
    snapshot_key = "sync"

    def __init__(self, db: Any, bus: Any, sensors: Any, hub: Any, activity: Any, workspace_provider):
        self.db = db
        self.sensors = sensors
        self.hub = hub
        self.activity = activity
        self.workspace = workspace_provider
        self.alignments: dict[str, ClockAlignment] = {}
        self.state: dict = {"measuring": False, "phase": "idle", "message": "", "sensor_ids": []}
        self._thread: threading.Thread | None = None
        bus.subscribe("sync", self._on_samples)

    def _on_samples(self, sensor_id: str, samples: list) -> None:
        alignment = self.alignments.get(sensor_id)
        if alignment is None:
            alignment = self.alignments[sensor_id] = ClockAlignment()
        alignment.add(samples)

    def alignment(self, sensor_id: str) -> dict:
        alignment = self.alignments.get(sensor_id)
        return alignment.fit() if alignment else {"ready": False, "points": 0}

    def snapshot(self) -> dict:
        return {**self.state, "alignments": {sid: self.alignment(sid) for sid in list(self.sensors.sessions)}, "measurements": self.measurements(5)}

    def measurements(self, limit: int = 20) -> list[dict]:
        with self.db() as db:
            rows = db.scalars(select(SyncMeasurementRow).where(SyncMeasurementRow.workspace == self.workspace()).order_by(SyncMeasurementRow.created_at.desc()).limit(limit)).all()
            return [self._dict(r) for r in rows]

    def _dict(self, r: SyncMeasurementRow) -> dict:
        return {"measurement_id": r.measurement_id, "sensor_ids": r.sensor_ids, "method": r.method, "events_used": r.events_used, "mean_abs_error_ms": r.mean_abs_error_ms, "max_abs_error_ms": r.max_abs_error_ms, "details": r.details, "created_at": iso(r.created_at), "workspace": r.workspace}

    def gate(self, sensor_ids: list[str]) -> dict:
        pair = sorted(sensor_ids)
        for m in self.measurements(50):
            if sorted(m["sensor_ids"]) == pair:
                allowed = m["max_abs_error_ms"] is not None and m["max_abs_error_ms"] <= COMBINED_MAX_ERROR_MS and m["events_used"] >= 3
                return {
                    "sensor_ids": pair,
                    "latest_measurement": m,
                    "combined_inference_allowed": allowed,
                    "threshold_ms": COMBINED_MAX_ERROR_MS,
                    "reason": "Measured alignment is within the threshold" if allowed else f"Measured max error {m['max_abs_error_ms']} ms exceeds {COMBINED_MAX_ERROR_MS} ms or too few events",
                    "simulated": bool(m["details"].get("simulated")),
                }
        return {"sensor_ids": pair, "latest_measurement": None, "combined_inference_allowed": False, "threshold_ms": COMBINED_MAX_ERROR_MS, "reason": "No synchronization measurement recorded for this sensor pair", "simulated": False}

    def start_measurement(self, sensor_ids: list[str], duration_s: float, demo_taps: int = 0) -> dict:
        if self.state["measuring"]:
            raise conflict("sync_busy", "A synchronization measurement is already running")
        if len(set(sensor_ids)) != 2:
            raise AppError("two_sensors_required", "Choose exactly two different sensors", 422)
        for sid in sensor_ids:
            if self.sensors.get(sid).status != "streaming":
                raise conflict("sensor_not_streaming", f"Sensor {sid} must be streaming")
            if not self.alignment(sid)["ready"]:
                raise conflict("alignment_not_ready", f"Sensor {sid} needs a few seconds of streaming before alignment is available")
        self.state = {"measuring": True, "phase": "collecting", "message": "Tap both sensors together firmly, about once per second", "sensor_ids": list(sensor_ids), "started": time.time(), "duration_s": duration_s}
        self.hub.publish("sync", "sync", self.snapshot())
        self._thread = threading.Thread(target=self._measure, args=(list(sensor_ids), duration_s, demo_taps), name="sync-measure", daemon=True)
        self._thread.start()
        return self.state

    def _measure(self, sensor_ids: list[str], duration_s: float, demo_taps: int) -> None:
        try:
            if demo_taps:
                sessions = [self.sensors.get(sid) for sid in sensor_ids]
                if not all(s.demo for s in sessions):
                    raise conflict("demo_only", "Simulated taps are only available for DEMO sensors")
                spacing = duration_s / (demo_taps + 1)
                for _ in range(demo_taps):
                    time.sleep(spacing)
                    for s in sessions:
                        s.demo.perform("sync_tap")
                time.sleep(max(0.5, spacing))
            else:
                time.sleep(duration_s)
            host_events: dict[str, list[float]] = {}
            for sid in sensor_ids:
                session = self.sensors.get(sid)
                t, _h, v = session.buffer.window(duration_s + 2)
                events = np.array(detect_impulses(t, v))
                host_events[sid] = (self.alignments[sid].device_to_host_us(events) / 1000.0).tolist() if len(events) else []
            a, b = host_events[sensor_ids[0]], host_events[sensor_ids[1]]
            errors = []
            for ta in a:
                if not b:
                    break
                tb = min(b, key=lambda x: abs(x - ta))
                if abs(tb - ta) <= PAIR_WINDOW_MS:
                    errors.append(ta - tb)
            simulated = all(self.sensors.get(sid).simulated for sid in sensor_ids)
            details = {
                "events": {sid: len(e) for sid, e in host_events.items()},
                "errors_ms": errors,
                "std_ms": float(np.std(errors)) if errors else None,
                "pair_window_ms": PAIR_WINDOW_MS,
                "alignment": {sid: self.alignment(sid) for sid in sensor_ids},
                "simulated": simulated,
                "note": "Simulated sensors share the host clock; this demonstrates the procedure, not hardware accuracy." if simulated else "Measured on hardware with simultaneous taps",
            }
            with self.db.begin() as db:
                row = SyncMeasurementRow(
                    measurement_id=new_id("sync"),
                    workspace=self.workspace(),
                    sensor_ids=sorted(sensor_ids),
                    method="simultaneous_taps_host_envelope_v1",
                    events_used=len(errors),
                    mean_abs_error_ms=float(np.mean(np.abs(errors))) if errors else None,
                    max_abs_error_ms=float(np.max(np.abs(errors))) if errors else None,
                    details=details,
                )
                db.add(row)
            message = f"Measured {len(errors)} paired event(s)" + (f"; max error {max(abs(e) for e in errors):.1f} ms" if errors else "; no paired events found")
            self.activity.info("sync", message, simulated=simulated)
            self.state = {"measuring": False, "phase": "done", "message": message, "sensor_ids": sensor_ids}
        except Exception as exc:
            self.state = {"measuring": False, "phase": "failed", "message": str(exc), "sensor_ids": sensor_ids}
        self.hub.publish("sync", "sync", self.snapshot())
