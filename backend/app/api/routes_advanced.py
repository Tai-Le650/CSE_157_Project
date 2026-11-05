from __future__ import annotations

import os
import threading
import time

import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ..ml.airwriting import load_templates, nearest, preprocess
from ..processing.activation import UNAVAILABLE_REASON
from .deps import Container
from .errors import AppError, conflict

advanced = APIRouter(prefix="/api/advanced", tags=["advanced"])

BLE_REASON = (
    "No firmware in this project exposes a BLE GATT service for IMU data, and no service/characteristic UUIDs or packet format "
    "are documented. BLE stays disabled (Bleak is not installed) until compatible firmware and GATT details exist."
)


class SyncMeasureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sensor_ids: list[str] = Field(min_length=2, max_length=2)
    duration_s: float = Field(10.0, ge=3, le=60)
    simulated_taps: int = Field(0, ge=0, le=20, description="Demo Mode only: inject this many simultaneous taps")


class CursorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sensor_id: str = Field(min_length=1, max_length=32)
    seconds: float = Field(2.0, ge=1, le=10)


class AirwritingClassify(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str = Field(min_length=1, max_length=96)
    recording_id: str | None = Field(None, max_length=96)
    sensor_id: str | None = Field(None, max_length=32)
    seconds: float = Field(2.0, ge=0.5, le=10)


_cpu_lock = threading.Lock()
_cpu_last: dict = {}


@advanced.get("/capabilities", summary="What advanced features are available, verified or unavailable")
def capabilities(c: Container) -> dict:
    sound_available, sound_reason = c.sound.available()
    return {
        "dual_sensor_recording": {"available": True, "verified_on_hardware": False, "note": "Select two streaming sensors in the recorder; each sensor gets its own file and clock, linked by capture_id."},
        "clock_alignment": {"available": True, "verified_on_hardware": False, "note": "Per-sensor host-clock mapping from the lower envelope of receive delays; measure accuracy with simultaneous taps."},
        "combined_inference": {"available": False, "reason": "Combined two-sensor models are not implemented. The synchronization gate below records whether a measured alignment would allow them."},
        "ble": {"available": False, "reason": BLE_REASON},
        "sound_activation": {"available": sound_available, "reason": sound_reason, "simulated_only": c.workspace() == "demo"},
        "cursor": {"available": True, "verified_on_hardware": False, "note": "Gyro-rate cursor control through the PC-control gate; calibrate while still."},
        "air_writing": {"available": True, "experimental": True, "verified_on_hardware": False, "note": "1-NN DTW baseline on gyro sequences; train with feature_version airwriting-dtw-v1 on trials labelled per character."},
    }


@advanced.get("/sync", summary="Clock alignment per sensor and recent synchronization measurements")
def sync_state(c: Container) -> dict:
    return c.sync.snapshot()


@advanced.post("/sync/measure", summary="Measure two-sensor alignment with simultaneous taps")
def sync_measure(body: SyncMeasureRequest, c: Container) -> dict:
    if body.simulated_taps and c.workspace() != "demo":
        raise conflict("demo_only", "Simulated taps are only available in Demo Mode")
    return c.sync.start_measurement(body.sensor_ids, body.duration_s, body.simulated_taps)


@advanced.get("/sync/gate", summary="Whether a recorded measurement would permit combined inference for a sensor pair")
def sync_gate(c: Container, a: str, b: str) -> dict:
    return c.sync.gate([a, b])


@advanced.get("/cursor", summary="Cursor-mode state and calibration")
def cursor_state(c: Container) -> dict:
    return c.cursor.snapshot()


@advanced.post("/cursor/calibrate", summary="Measure gyro bias while the sensor is held still")
def cursor_calibrate(body: CursorRequest, c: Container) -> dict:
    return c.cursor.calibrate(body.sensor_id, body.seconds)


@advanced.post("/cursor/start", summary="Start cursor mode (PC control must be armed)")
def cursor_start(body: CursorRequest, c: Container) -> dict:
    return c.cursor.start(body.sensor_id)


@advanced.post("/cursor/stop", summary="Stop cursor mode")
def cursor_stop(c: Container) -> dict:
    return c.cursor.stop("user")


@advanced.get("/sound", summary="Sound-activation availability and state")
def sound_state(c: Container) -> dict:
    return c.sound.snapshot()


@advanced.post("/sound/demo/start", summary="Start the simulated microphone (Demo Mode only)")
def sound_start(c: Container) -> dict:
    return c.sound.start_demo_source()


@advanced.post("/sound/demo/stop", summary="Stop the simulated microphone")
def sound_stop(c: Container) -> dict:
    return c.sound.stop_source()


@advanced.post("/sound/demo/clap", summary="Inject a simulated activation sound")
def sound_clap(c: Container) -> dict:
    return c.sound.demo_clap()


@advanced.post("/airwriting/classify", summary="Classify a recording or the last seconds of live data with an air-writing model (experimental)")
def airwriting_classify(body: AirwritingClassify, c: Container) -> dict:
    detail = c.registry.detail(body.model_id)
    if detail["feature_version"] != "airwriting-dtw-v1":
        raise conflict("not_airwriting_model", "Choose an air-writing (airwriting-dtw-v1) model")
    if not detail["trusted"]:
        raise conflict("model_untrusted", "Model is not trusted")
    templates, labels = load_templates(c.registry._path_by_id(body.model_id))
    if body.recording_id:
        _row, signal = c.library.signal_for(body.recording_id)
        t, v = signal.t_us, signal.values
        source = {"recording_id": body.recording_id}
    elif body.sensor_id:
        session = c.sensors.get(body.sensor_id)
        t, _h, v = session.buffer.window(body.seconds)
        source = {"sensor_id": body.sensor_id, "seconds": body.seconds, "simulated": session.simulated}
    else:
        raise AppError("source_required", "Provide recording_id or sensor_id", 422)
    try:
        sequence = preprocess(t, v)
    except ValueError as exc:
        raise conflict("insufficient_samples", str(exc))
    return {**source, **nearest(templates, labels, sequence), "experimental": True}


@advanced.get("/performance", summary="Measured backend CPU use, threads, WebSocket drops and recognition latency")
def performance(c: Container) -> dict:
    now = time.monotonic()
    times = os.times()
    cpu = times.user + times.system
    with _cpu_lock:
        last = dict(_cpu_last)
        _cpu_last.update({"wall": now, "cpu": cpu})
    cpu_percent = None
    if last:
        wall = now - last["wall"]
        if wall > 0.2:
            cpu_percent = 100.0 * (cpu - last["cpu"]) / wall
    latencies = [h["latency_ms"] for h in list(c.recognition.history)]
    return {
        "measured_at": time.time(),
        "process_cpu_percent_since_last_call": cpu_percent,
        "process_cpu_seconds_total": cpu,
        "threads": threading.active_count(),
        "websocket_clients": c.hub.client_count,
        "ui_frames_dropped": c.hub.ui_frames_dropped,
        "ui_samples_dropped": c.hub.ui_samples_dropped,
        "bus_subscriber_errors": c.bus.errors,
        "recognition": {
            "running": c.recognition.running,
            "windows": c.recognition.counters.get("windows", 0),
            "latency_ms_mean": float(np.mean(latencies)) if latencies else None,
            "latency_ms_p95": float(np.percentile(latencies, 95)) if latencies else None,
            "last_processing_ms": (c.recognition.last_prediction or {}).get("processing_ms"),
        },
        "sensors": {s.sensor_id: {"device_hz": s.last_rates.get("device_hz"), "arrival_hz": s.last_rates.get("arrival_hz"), "valid_samples": s.good_samples} for s in c.sensors.sessions.values()},
        "note": "Values are measured in this process on this machine; end-to-end motion-to-action latency is not measured.",
    }


@advanced.get("/sound/requirements", summary="Why sound activation is unavailable with the current firmware")
def sound_requirements() -> dict:
    return {"reason": UNAVAILABLE_REASON}
