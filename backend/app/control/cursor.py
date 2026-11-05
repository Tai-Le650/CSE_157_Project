from __future__ import annotations

import threading
import time
from typing import Any

import numpy as np

from ..api.errors import AppError, conflict
from .actions import MouseMoveAction

AXIS_INDEX = {"gx": 3, "gy": 4, "gz": 5}
TICK_S = 0.02
MAX_STEP_PX = 400


def cursor_velocity(rate_dps: float, bias_dps: float, dead_zone_dps: float, gain_px_per_deg: float, max_speed_px_s: float, invert: bool) -> float:
    corrected = rate_dps - bias_dps
    if abs(corrected) <= dead_zone_dps:
        return 0.0
    corrected = corrected - np.sign(corrected) * dead_zone_dps
    velocity = gain_px_per_deg * corrected
    velocity = float(np.clip(velocity, -max_speed_px_s, max_speed_px_s))
    return -velocity if invert else velocity


class CursorController:
    snapshot_key = "cursor"

    def __init__(self, sensors: Any, settings: Any, control: Any, hub: Any, activity: Any):
        self.sensors = sensors
        self.settings = settings
        self.control = control
        self.hub = hub
        self.activity = activity
        self.active = False
        self.sensor_id: str | None = None
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.moves = 0
        self.last_velocity = (0.0, 0.0)
        self.message = "Cursor mode off"
        sensors.add_listener(self._on_sensor_event)

    def snapshot(self) -> dict:
        cursor = self.settings.current.cursor
        return {
            "active": self.active,
            "sensor_id": self.sensor_id,
            "moves": self.moves,
            "last_velocity_px_s": self.last_velocity,
            "message": self.message,
            "calibrated": cursor.calibrated_at is not None,
            "calibrated_sensor_id": cursor.calibrated_sensor_id,
            "calibrated_at": cursor.calibrated_at,
            "settings": cursor.model_dump(),
            "verified_on_hardware": False,
        }

    def publish(self) -> None:
        self.hub.publish("cursor", "cursor", self.snapshot())

    def calibrate(self, sensor_id: str, seconds: float = 2.0) -> dict:
        session = self.sensors.get(sensor_id)
        if session.status != "streaming":
            raise conflict("sensor_not_streaming", f"Sensor {sensor_id} must be streaming")
        time.sleep(seconds)
        t, _h, v = session.buffer.window(seconds)
        if len(t) < 20:
            raise conflict("insufficient_samples", "Not enough samples for calibration")
        gyro = v[:, 3:6]
        noise = np.std(gyro, axis=0)
        if float(np.max(noise)) > 5.0:
            raise conflict("not_still", f"The sensor moved during calibration (gyro noise {np.max(noise):.1f} deg/s). Keep it still and retry.")
        bias = np.mean(gyro, axis=0)
        suggested = float(max(2.0, 3 * float(np.max(noise))))
        cursor = self.settings.current.cursor.model_dump()
        cursor.update({
            "bias_dps": {"gx": float(bias[0]), "gy": float(bias[1]), "gz": float(bias[2])},
            "noise_dps": {"gx": float(noise[0]), "gy": float(noise[1]), "gz": float(noise[2])},
            "calibrated_sensor_id": sensor_id,
            "calibrated_at": time.time(),
            "dead_zone_dps": max(cursor["dead_zone_dps"], suggested),
        })
        self.settings.update({"cursor": cursor})
        self.activity.info("cursor", f"Cursor calibrated on {sensor_id}: bias {np.round(bias, 2).tolist()} deg/s, suggested dead zone {suggested:.1f} deg/s")
        self.publish()
        return {**self.snapshot(), "suggested_dead_zone_dps": suggested, "samples": int(len(t))}

    def start(self, sensor_id: str) -> dict:
        if self.active:
            raise conflict("cursor_active", "Cursor mode is already running")
        session = self.sensors.get(sensor_id)
        if session.status != "streaming":
            raise conflict("sensor_not_streaming", f"Sensor {sensor_id} must be streaming")
        cursor = self.settings.current.cursor
        if cursor.calibrated_sensor_id != sensor_id:
            raise conflict("calibration_required", "Calibrate this sensor while holding it still before using cursor mode")
        if not self.control.armed:
            raise conflict("not_armed", "Arm PC control first; cursor moves go through the same safety gate")
        self.sensor_id = sensor_id
        self.stop_event = threading.Event()
        self.active = True
        self.moves = 0
        self.message = "Cursor mode on"
        self.thread = threading.Thread(target=self._loop, name="cursor", daemon=True)
        self.thread.start()
        self.activity.warning("cursor", f"Cursor mode ON using {sensor_id}")
        self.publish()
        return self.snapshot()

    def stop(self, reason: str = "user") -> dict:
        if not self.active:
            return self.snapshot()
        self.stop_event.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
        self.active = False
        self.message = f"Cursor mode off ({reason})"
        self.activity.info("cursor", self.message)
        self.publish()
        return self.snapshot()

    def on_shutdown(self) -> None:
        self.stop("shutdown")

    def _on_sensor_event(self, event: str, sensor_id: str, _data: dict) -> None:
        if self.active and sensor_id == self.sensor_id and event in ("lost", "stalled", "disconnected"):
            threading.Thread(target=self.stop, args=(f"sensor {event}",), daemon=True).start()

    def _loop(self) -> None:
        carry_x = carry_y = 0.0
        last_t: float | None = None
        while not self.stop_event.wait(TICK_S):
            if not self.control.armed:
                threading.Thread(target=self.stop, args=("disarmed",), daemon=True).start()
                return
            session = self.sensors.sessions.get(self.sensor_id)
            if session is None:
                return
            t, _h, v = session.buffer.window(0.5)
            if len(t) == 0:
                continue
            if last_t is None:
                last_t = float(t[-1])
                continue
            new = t > last_t
            if not new.any():
                continue
            cfg = self.settings.current.cursor
            rows = v[new]
            times = t[new]
            dt = np.diff(np.r_[last_t, times]) / 1e6
            last_t = float(times[-1])
            vx = np.array([cursor_velocity(r[AXIS_INDEX[cfg.x_axis]], cfg.bias_dps.get(cfg.x_axis, 0.0), cfg.dead_zone_dps, cfg.gain_px_per_deg, cfg.max_speed_px_s, cfg.invert_x) for r in rows])
            vy = np.array([cursor_velocity(r[AXIS_INDEX[cfg.y_axis]], cfg.bias_dps.get(cfg.y_axis, 0.0), cfg.dead_zone_dps, cfg.gain_px_per_deg, cfg.max_speed_px_s, cfg.invert_y) for r in rows])
            carry_x += float(np.sum(vx * dt))
            carry_y += float(np.sum(vy * dt))
            self.last_velocity = (float(vx[-1]), float(vy[-1]))
            dx, dy = int(carry_x), int(carry_y)
            if dx == 0 and dy == 0:
                continue
            carry_x -= dx
            carry_y -= dy
            dx = max(-MAX_STEP_PX, min(MAX_STEP_PX, dx))
            dy = max(-MAX_STEP_PX, min(MAX_STEP_PX, dy))
            outcome = self.control.submit("cursor", MouseMoveAction(dx=dx, dy=dy), None, source="cursor", sensor_id=self.sensor_id)
            if outcome == "queued":
                self.moves += 1
