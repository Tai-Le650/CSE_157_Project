from __future__ import annotations

import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from ..api.errors import AppError, conflict, not_found
from .buffers import RingBuffer
from .bus import SampleBus
from .demo_device import DEMO_PREFIX, DemoSerial
from .stream import Sample, StreamReader

SENSOR_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
HANDS = ("left", "right", "unassigned")
ACTIVE_STATUSES = ("connecting", "waiting_for_data", "streaming", "stalled")
FIRMWARE_HINTS = {
    "t_us": "Header t_us matches firmware/gesture_stream (documented: ±16 g, ±2000 dps)",
    "time_us": "Header time_us matches imu_capture.ino (documented: ±4 g, ±500 dps)",
}


class RateTracker:
    def __init__(self, horizon_s: float = 5.0):
        self.horizon_ns = int(horizon_s * 1e9)
        self.entries: deque[tuple[int, float, int]] = deque()
        self.lock = threading.Lock()

    def add(self, samples: list[Sample]) -> None:
        with self.lock:
            for s in samples:
                if s.good and s.t_us is not None:
                    self.entries.append((s.host_ns, s.t_us, s.epoch))

    def rates(self, now_ns: int) -> dict:
        with self.lock:
            while self.entries and now_ns - self.entries[0][0] > self.horizon_ns:
                self.entries.popleft()
            entries = list(self.entries)
        if len(entries) < 3:
            return {"device_hz": None, "arrival_hz": None, "window_samples": len(entries)}
        epoch = entries[-1][2]
        same = [e for e in entries if e[2] == epoch]
        device_hz = None
        if len(same) >= 3:
            span_s = (same[-1][1] - same[0][1]) / 1e6
            if span_s >= 0.5:
                device_hz = (len(same) - 1) / span_s
        host_span_s = (entries[-1][0] - entries[0][0]) / 1e9
        arrival_hz = (len(entries) - 1) / host_span_s if host_span_s >= 0.5 else None
        return {"device_hz": device_hz, "arrival_hz": arrival_hz, "window_samples": len(entries)}


@dataclass
class SensorSession:
    sensor_id: str
    port: str
    baud: int
    hand: str
    workspace: str
    simulated: bool
    demo_options: dict = field(default_factory=dict)
    status: str = "connecting"
    error: dict | None = None
    reader: StreamReader | None = None
    demo: DemoSerial | None = None
    buffer: RingBuffer = field(default_factory=RingBuffer)
    rates: RateTracker = field(default_factory=RateTracker)
    connected_at: float | None = None
    last_good_host_ns: int | None = None
    first_device_t_us: int | None = None
    last_device_t_raw: int | None = None
    last_epoch: int | None = None
    user_disconnected: bool = False
    reconnect_attempts: int = 0
    stalls: int = 0
    disconnects: int = 0
    header_alias: str | None = None
    last_diagnostic: str | None = None
    device_error: str | None = None
    last_rates: dict = field(default_factory=lambda: {"device_hz": None, "arrival_hz": None, "window_samples": 0})
    total_samples: int = 0
    good_samples: int = 0

    @property
    def active(self) -> bool:
        return self.status in ACTIVE_STATUSES


Listener = Callable[[str, str, dict], None]


class SensorManager:
    def __init__(
        self,
        bus: SampleBus,
        hub: Any,
        activity: Any,
        workspace_provider: Callable[[], str],
        auto_reconnect_provider: Callable[[], bool],
        stall_timeout_provider: Callable[[], float],
        opener: Callable[[str, int], Any] | None = None,
        health_interval_s: float = 0.5,
    ):
        self.bus = bus
        self.hub = hub
        self.activity = activity
        self.workspace_provider = workspace_provider
        self.auto_reconnect_provider = auto_reconnect_provider
        self.stall_timeout_provider = stall_timeout_provider
        self.opener = opener
        self.health_interval_s = health_interval_s
        self.sessions: dict[str, SensorSession] = {}
        self.lock = threading.RLock()
        self.listeners: list[Listener] = []
        self._stop = threading.Event()
        self._health: threading.Thread | None = None
        self._tick = 0

    def add_listener(self, listener: Listener) -> None:
        self.listeners.append(listener)

    def _notify(self, event: str, sensor_id: str, data: dict | None = None) -> None:
        for listener in list(self.listeners):
            try:
                listener(event, sensor_id, data or {})
            except Exception:
                pass

    def start(self) -> None:
        self._stop.clear()
        self._health = threading.Thread(target=self._health_loop, name="sensor-health", daemon=True)
        self._health.start()

    def stop(self) -> None:
        self._stop.set()
        for sensor_id in list(self.sessions):
            try:
                self.disconnect(sensor_id, reason="shutdown")
            except AppError:
                pass
        if self._health:
            self._health.join(timeout=2)

    def get(self, sensor_id: str) -> SensorSession:
        session = self.sessions.get(sensor_id)
        if session is None:
            raise not_found("Sensor", sensor_id)
        return session

    def active_sessions(self) -> list[SensorSession]:
        return [s for s in self.sessions.values() if s.active]

    def owned_ports(self) -> dict[str, str]:
        return {s.port: s.sensor_id for s in self.sessions.values() if s.active}

    def connect(self, port: str | None, baud: int, sensor_id: str, hand: str = "unassigned", simulated: bool = False, demo_options: dict | None = None) -> SensorSession:
        workspace = self.workspace_provider()
        if simulated and not sensor_id.startswith(DEMO_PREFIX):
            sensor_id = f"{DEMO_PREFIX}{sensor_id}"
        if not SENSOR_ID_RE.match(sensor_id):
            raise AppError("invalid_sensor_id", "Sensor IDs use 1-32 letters, digits, '-' or '_' and start with a letter or digit", 422)
        if hand not in HANDS:
            raise AppError("invalid_hand", f"Hand must be one of {', '.join(HANDS)}", 422)
        if workspace == "demo" and not simulated:
            raise conflict("demo_mode_blocks_real_ports", "Demo Mode is on: only simulated (DEMO-*) sensors can connect. Turn Demo Mode off in Settings to use a real board.")
        if workspace == "real" and simulated:
            raise conflict("simulated_requires_demo_mode", "Simulated sensors are only available in Demo Mode.")
        if not simulated and not port:
            raise AppError("port_required", "Select a COM port", 422)
        if simulated:
            port = f"demo://{sensor_id}"
        if not simulated and sensor_id.upper().startswith(DEMO_PREFIX):
            raise AppError("reserved_sensor_id", "IDs starting with DEMO- are reserved for simulated sensors", 422)
        with self.lock:
            existing = self.sessions.get(sensor_id)
            if existing is not None and existing.active:
                raise conflict("sensor_id_in_use", f"Sensor ID '{sensor_id}' is already connected on {existing.port}")
            owner = self.owned_ports().get(port)
            if owner is not None:
                raise conflict("port_owned", f"{port} is already owned by sensor '{owner}'. One acquisition owner per port.")
            session = SensorSession(
                sensor_id=sensor_id,
                port=port,
                baud=baud,
                hand=hand,
                workspace=workspace,
                simulated=simulated,
                demo_options=dict(demo_options or {}),
            )
            self.sessions[sensor_id] = session
            self._start_reader(session)
        self.activity.info("sensor", f"Connecting {sensor_id} on {port} at {baud} baud", sensor_id=sensor_id, port=port, simulated=simulated)
        self.publish_connections()
        return session

    def _start_reader(self, session: SensorSession) -> None:
        if session.simulated:
            demo = DemoSerial(**session.demo_options)
            session.demo = demo
            opener = lambda: demo
        else:
            port, baud = session.port, session.baud
            opener = lambda: self._open_serial(port, baud)
        session.buffer = RingBuffer()
        session.rates = RateTracker()
        session.status = "connecting"
        session.error = None
        session.user_disconnected = False
        session.last_good_host_ns = None
        session.first_device_t_us = None
        reader_ref: dict[str, StreamReader] = {}

        def on_samples(_sid: str, batch: list[Sample]) -> None:
            self._on_samples(reader_ref["reader"], session, batch)

        def on_event(_sid: str, event: str, data: dict) -> None:
            self._on_event(reader_ref["reader"], session, event, data)

        reader = StreamReader(session.sensor_id, opener, on_samples, on_event)
        reader_ref["reader"] = reader
        session.reader = reader
        reader.start()

    def _open_serial(self, port: str, baud: int) -> Any:
        if self.opener is not None:
            return self.opener(port, baud)
        import serial

        return serial.Serial(port=port, baudrate=baud, timeout=0.05)

    def disconnect(self, sensor_id: str, reason: str = "user") -> SensorSession:
        session = self.get(sensor_id)
        reader = session.reader
        session.user_disconnected = True
        if reader is not None:
            reader.stop()
            if reader is not threading.current_thread():
                reader.join(timeout=3)
        was_active = session.active
        session.status = "disconnected"
        if was_active or reason == "user":
            self.activity.info("sensor", f"Disconnected {sensor_id} ({reason})", sensor_id=sensor_id, reason=reason)
        self._notify("disconnected", sensor_id, {"reason": reason})
        self.publish_connections()
        return session

    def remove(self, sensor_id: str) -> None:
        session = self.get(sensor_id)
        if session.active:
            self.disconnect(sensor_id)
        with self.lock:
            self.sessions.pop(sensor_id, None)
        self.publish_connections()

    def reconnect(self, sensor_id: str) -> SensorSession:
        session = self.get(sensor_id)
        if session.active:
            self.disconnect(sensor_id, reason="reconnect")
        workspace = self.workspace_provider()
        if session.simulated != (workspace == "demo"):
            raise conflict("workspace_mismatch", "This sensor belongs to the other mode (Demo vs real). Switch modes first.")
        with self.lock:
            owner = self.owned_ports().get(session.port)
            if owner is not None and owner != sensor_id:
                raise conflict("port_owned", f"{session.port} is already owned by sensor '{owner}'")
            self._start_reader(session)
        self.activity.info("sensor", f"Reconnecting {sensor_id} on {session.port}", sensor_id=sensor_id)
        self.publish_connections()
        return session

    def update(self, sensor_id: str, new_sensor_id: str | None = None, hand: str | None = None) -> SensorSession:
        session = self.get(sensor_id)
        if hand is not None:
            if hand not in HANDS:
                raise AppError("invalid_hand", f"Hand must be one of {', '.join(HANDS)}", 422)
            session.hand = hand
        if new_sensor_id and new_sensor_id != sensor_id:
            if session.active:
                raise conflict("rename_requires_disconnect", "Disconnect the sensor before changing its ID")
            if not SENSOR_ID_RE.match(new_sensor_id):
                raise AppError("invalid_sensor_id", "Sensor IDs use 1-32 letters, digits, '-' or '_'", 422)
            if session.simulated and not new_sensor_id.startswith(DEMO_PREFIX):
                new_sensor_id = f"{DEMO_PREFIX}{new_sensor_id}"
            if not session.simulated and new_sensor_id.upper().startswith(DEMO_PREFIX):
                raise AppError("reserved_sensor_id", "IDs starting with DEMO- are reserved for simulated sensors", 422)
            with self.lock:
                if new_sensor_id in self.sessions:
                    raise conflict("sensor_id_in_use", f"Sensor ID '{new_sensor_id}' already exists")
                self.sessions.pop(sensor_id)
                session.sensor_id = new_sensor_id
                if session.simulated:
                    session.port = f"demo://{new_sensor_id}"
                self.sessions[new_sensor_id] = session
        self.publish_connections()
        return session

    def _on_samples(self, reader: StreamReader, session: SensorSession, batch: list[Sample]) -> None:
        if session.reader is not reader:
            return
        session.buffer.append(batch)
        session.rates.add(batch)
        good_rows = []
        for s in batch:
            session.total_samples += 1
            session.last_device_t_raw = s.t_raw
            if s.good and s.t_us is not None:
                session.good_samples += 1
                session.last_good_host_ns = s.host_ns
                if session.first_device_t_us is None or session.last_epoch != s.epoch:
                    session.first_device_t_us = s.t_raw
                    session.last_epoch = s.epoch
                good_rows.append((int(s.t_us), s.epoch, *s.values))
        if good_rows and session.status in ("connecting", "waiting_for_data", "stalled"):
            previous = session.status
            session.status = "streaming"
            if previous == "stalled":
                self.activity.info("sensor", f"{session.sensor_id} recovered from stall", sensor_id=session.sensor_id)
                self._notify("recovered", session.sensor_id)
            self.publish_connections()
        self.bus.publish(session.sensor_id, batch)
        if good_rows:
            self.hub.push_samples(session.sensor_id, good_rows, {"simulated": session.simulated})

    def _on_event(self, reader: StreamReader, session: SensorSession, event: str, data: dict) -> None:
        if session.reader is not reader:
            return
        sid = session.sensor_id
        if event == "opened":
            session.status = "waiting_for_data"
            session.connected_at = time.time()
            session.reconnect_attempts = 0
            self.activity.info("sensor", f"{sid} port opened; waiting for data", sensor_id=sid)
            self._notify("connected", sid)
        elif event == "header":
            session.header_alias = data.get("alias")
            self.activity.info("sensor", f"{sid} sent header '{session.header_alias}' (device boot or reset)", sensor_id=sid)
        elif event == "diagnostic":
            session.last_diagnostic = data.get("text")
            if data.get("is_error"):
                session.device_error = data.get("text")
                self.activity.error("sensor", f"{sid} device reported: {data.get('text')}", sensor_id=sid)
        elif event == "open_failed":
            session.status = "error"
            session.error = data.get("error")
            self.activity.error("sensor", f"{sid} could not open {session.port}: {session.error.get('message') if session.error else ''}", sensor_id=sid, error=session.error)
            self._notify("open_failed", sid, data)
        elif event == "lost":
            session.status = "disconnected"
            session.error = data.get("error")
            session.disconnects += 1
            self.activity.warning("sensor", f"{sid} connection lost", sensor_id=sid, error=session.error)
            self._notify("lost", sid, data)
            if self.auto_reconnect_provider() and not session.user_disconnected:
                self._schedule_reconnect(session)
        elif event == "closed":
            if not session.user_disconnected:
                session.status = "disconnected"
                self._notify("lost", sid, {"error": {"code": "closed", "message": "Stream closed"}})
        self.publish_connections()

    def _schedule_reconnect(self, session: SensorSession) -> None:
        if session.reconnect_attempts >= 10:
            self.activity.warning("sensor", f"Auto-reconnect gave up for {session.sensor_id} after 10 attempts", sensor_id=session.sensor_id)
            return
        session.reconnect_attempts += 1
        attempt = session.reconnect_attempts

        def retry() -> None:
            if self._stop.is_set() or session.user_disconnected or session.active:
                return
            if self.sessions.get(session.sensor_id) is not session:
                return
            self.activity.info("sensor", f"Auto-reconnect attempt {attempt} for {session.sensor_id}", sensor_id=session.sensor_id)
            with self.lock:
                if self.owned_ports().get(session.port):
                    return
                self._start_reader(session)
                session.reconnect_attempts = attempt
            self.publish_connections()

        timer = threading.Timer(2.0, retry)
        timer.daemon = True
        timer.start()

    def _health_loop(self) -> None:
        while not self._stop.wait(self.health_interval_s):
            self._tick += 1
            now_ns = time.perf_counter_ns()
            stall_timeout = self.stall_timeout_provider()
            changed = False
            for session in list(self.sessions.values()):
                session.last_rates = session.rates.rates(now_ns)
                if session.status == "streaming" and session.last_good_host_ns is not None:
                    if (now_ns - session.last_good_host_ns) / 1e9 > stall_timeout:
                        session.status = "stalled"
                        session.stalls += 1
                        changed = True
                        self.activity.warning("sensor", f"{session.sensor_id} stalled: no valid samples for {stall_timeout:.1f} s", sensor_id=session.sensor_id)
                        self._notify("stalled", session.sensor_id)
            if changed or self._tick % 2 == 0:
                self.publish_connections()

    def describe(self, session: SensorSession) -> dict:
        reader = session.reader
        counters = reader.counters.as_dict() if reader else {}
        timing = reader.classifier.stats.as_dict() if reader else {}
        if reader:
            counters["partial_lines_dropped"] = reader.partial_lines_dropped()
            counters["line_overflows"] = reader.overflows()
            counters["rejected_examples"] = list(reader.counters.rejected_examples)[-5:]
            median_us = reader.classifier.median_us()
            timing["median_interval_us"] = median_us
            timing["median_interval_hz"] = 1e6 / median_us if median_us else None
        last_age = None
        if session.last_good_host_ns is not None:
            last_age = (time.perf_counter_ns() - session.last_good_host_ns) / 1e9
        return {
            "sensor_id": session.sensor_id,
            "port": session.port,
            "baud": session.baud,
            "hand": session.hand,
            "workspace": session.workspace,
            "simulated": session.simulated,
            "status": session.status,
            "error": session.error,
            "connected_at": session.connected_at,
            "header_alias": session.header_alias,
            "firmware_hint": FIRMWARE_HINTS.get(session.header_alias or "", None),
            "column_order_assumed": session.header_alias is None,
            "last_diagnostic": session.last_diagnostic,
            "device_error": session.device_error,
            "rates": session.last_rates,
            "counters": counters,
            "timing": timing,
            "clock": {
                "epoch": session.last_epoch,
                "first_device_t_us": session.first_device_t_us,
                "last_device_t_raw": session.last_device_t_raw,
                "last_valid_sample_age_s": last_age,
            },
            "totals": {"samples": session.total_samples, "valid_samples": session.good_samples, "stalls": session.stalls, "disconnects": session.disconnects, "reconnect_attempts": session.reconnect_attempts},
            "demo": {
                "current_gesture": session.demo.current_gesture if session.demo else None,
                "auto": session.demo.auto if session.demo else None,
                "rate_hz": session.demo.rate_hz if session.demo else None,
            } if session.simulated else None,
        }

    def snapshot(self) -> list[dict]:
        return [self.describe(s) for s in list(self.sessions.values())]

    def publish_connections(self) -> None:
        self.hub.publish("connections", "connections", {"sensors": self.snapshot()})
