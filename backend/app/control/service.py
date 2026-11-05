from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from ..api.errors import AppError, conflict
from .actions import MouseMoveAction, describe_action, parse_any_action
from .executor import FailSafeTriggered, SimulatedBackend
from .gate import GateInputs, gate_decision
from .hotkey import GlobalHotkey, hotkeys_supported

LOSS_EVENTS = ("lost", "stalled", "disconnected", "open_failed")


@dataclass
class ActionRequest:
    request_id: str
    label: str
    action: BaseModel
    detection_id: str | None
    source: str
    sensor_id: str | None
    generation: int
    workspace: str
    created: float = field(default_factory=time.monotonic)


class ControlService:
    def __init__(
        self,
        hub: Any,
        activity: Any,
        settings: Any,
        workspace_provider: Callable[[], str],
        backend_factory: Callable[[], Any],
        enable_global_hotkey: bool = True,
    ):
        self.hub = hub
        self.activity = activity
        self.settings = settings
        self.workspace_provider = workspace_provider
        self.backend_factory = backend_factory
        self.enable_global_hotkey = enable_global_hotkey
        self.lock = threading.RLock()
        self.wakeup = threading.Condition(self.lock)
        self.armed = False
        self.armed_at: float | None = None
        self.armed_workspace: str | None = None
        self.generation = 0
        self.estop_latched = False
        self.estop_reason: str | None = None
        self.estop_at: float | None = None
        self.control_session_id: str | None = None
        self.last_disarm_reason: str | None = None
        self.pending: deque[ActionRequest] = deque(maxlen=4)
        self.last_action_at: dict[str, float] = {}
        self.last_executed_at: float | None = None
        self.executed_detections: deque[str] = deque(maxlen=500)
        self.history: deque[dict] = deque(maxlen=200)
        self.counters = {"executed": 0, "simulated": 0, "blocked": 0, "errors": 0, "previewed": 0}
        self.prerequisites: Callable[[], list[str]] = lambda: []
        self.sensor_health: Callable[[str], bool] = lambda _sid: True
        self.activation_check: Callable[[], bool] = lambda: True
        self.monitored_sensors: Callable[[], set[str]] = lambda: set()
        self.cooldown_provider: Callable[[], float] = lambda: settings.current.inference.cooldown_s
        self._sim_backend = SimulatedBackend()
        self._real_backend: Any = None
        self.hotkey: GlobalHotkey | None = None
        self.hotkey_status: str = "inactive"
        self._stop = threading.Event()
        self._executor: threading.Thread | None = None
        self._monitor: threading.Thread | None = None

    def start(self) -> None:
        self._stop.clear()
        self._executor = threading.Thread(target=self._executor_loop, name="control-executor", daemon=True)
        self._monitor = threading.Thread(target=self._monitor_loop, name="control-monitor", daemon=True)
        self._executor.start()
        self._monitor.start()

    def stop(self) -> None:
        self.disarm("shutdown")
        self._stop.set()
        with self.wakeup:
            self.wakeup.notify_all()
        for thread in (self._executor, self._monitor):
            if thread:
                thread.join(timeout=2)

    def state(self) -> dict:
        settings = self.settings.current.control
        return {
            "pc_control_enabled": settings.pc_control_enabled,
            "armed": self.armed,
            "armed_at": self.armed_at,
            "workspace": self.workspace_provider(),
            "simulated_actions": self.workspace_provider() == "demo",
            "estop_latched": self.estop_latched,
            "estop_reason": self.estop_reason,
            "estop_at": self.estop_at,
            "control_session_id": self.control_session_id,
            "last_disarm_reason": self.last_disarm_reason,
            "generation": self.generation,
            "pending_actions": len(self.pending),
            "counters": dict(self.counters),
            "global_hotkey": {"spec": settings.global_estop_hotkey, "status": self.hotkey_status, "supported": hotkeys_supported()},
            "history": list(self.history)[-30:],
        }

    def publish(self) -> None:
        self.hub.publish("status", "control", self.state())

    def arm(self, control_session_id: str | None, confirm: bool) -> dict:
        reasons: list[str] = []
        control = self.settings.current.control
        if not control.pc_control_enabled:
            reasons.append("PC control is disabled in Settings (Settings → PC control → Allow PC control).")
        if self.estop_latched:
            reasons.append("Emergency Stop is latched. Reset it before arming.")
        if not confirm:
            reasons.append("Arming requires explicit confirmation.")
        if not control_session_id or not self.hub.has_client(control_session_id):
            reasons.append("No live control session. Keep the Gesture-to-PC tab open; it sends heartbeats.")
        try:
            reasons.extend(self.prerequisites())
        except Exception as exc:
            reasons.append(f"Prerequisite check failed: {exc}")
        if reasons:
            raise conflict("arm_blocked", "PC control cannot be armed", {"reasons": reasons})
        with self.lock:
            self.armed = True
            self.armed_at = time.time()
            self.armed_workspace = self.workspace_provider()
            self.generation += 1
            self.control_session_id = control_session_id
            self.pending.clear()
            self.last_executed_at = time.monotonic()
        self._register_hotkey()
        mode = "SIMULATED (Demo Mode)" if self.armed_workspace == "demo" else "REAL keyboard/mouse"
        self.activity.warning("control", f"PC control ARMED — {mode}", session=control_session_id)
        self.publish()
        return self.state()

    def disarm(self, reason: str) -> dict:
        with self.lock:
            was_armed = self.armed
            self.armed = False
            self.armed_at = None
            self.generation += 1
            self.pending.clear()
            self.control_session_id = None
            if was_armed:
                self.last_disarm_reason = reason
        self._unregister_hotkey()
        if was_armed:
            self.activity.warning("control", f"PC control disarmed ({reason})", reason=reason)
            self.publish()
        return self.state()

    def emergency_stop(self, source: str) -> dict:
        with self.lock:
            self.estop_latched = True
            self.estop_reason = source
            self.estop_at = time.time()
            self.armed = False
            self.armed_at = None
            self.generation += 1
            self.pending.clear()
            self.control_session_id = None
            self.last_disarm_reason = f"emergency_stop:{source}"
        self._unregister_hotkey()
        self.activity.error("control", f"EMERGENCY STOP ({source}) — all pending actions cleared", source=source)
        self.publish()
        return self.state()

    def reset_estop(self) -> dict:
        with self.lock:
            if not self.estop_latched:
                return self.state()
            self.estop_latched = False
            self.estop_reason = None
            self.estop_at = None
        self.activity.info("control", "Emergency Stop reset; PC control remains disarmed until armed again")
        self.publish()
        return self.state()

    def _register_hotkey(self) -> None:
        control = self.settings.current.control
        if not (self.enable_global_hotkey and control.global_hotkey_enabled and hotkeys_supported()):
            self.hotkey_status = "disabled" if hotkeys_supported() else "unsupported"
            return
        self._unregister_hotkey()
        try:
            hotkey = GlobalHotkey(control.global_estop_hotkey, lambda: self.emergency_stop("global_hotkey"))
        except ValueError as exc:
            self.hotkey_status = f"invalid: {exc}"
            return
        if hotkey.start():
            self.hotkey = hotkey
            self.hotkey_status = "registered"
        else:
            self.hotkey_status = hotkey.failed or "failed"
            self.activity.warning("control", f"Global E-stop hotkey unavailable: {self.hotkey_status}")

    def _unregister_hotkey(self) -> None:
        hotkey = self.hotkey
        self.hotkey = None
        if hotkey is not None:
            hotkey.stop()
        if self.hotkey_status == "registered":
            self.hotkey_status = "inactive"

    def submit(self, label: str, action: dict | BaseModel, detection_id: str | None, source: str = "gesture", sensor_id: str | None = None, is_idle: bool = False) -> str:
        try:
            parsed = action if isinstance(action, BaseModel) else parse_any_action(action)
        except ValidationError:
            self._record(label, None, detection_id, source, "blocked", "action_not_allowlisted")
            return "blocked"
        if is_idle:
            self._record(label, parsed, detection_id, source, "blocked", "idle_never_acts")
            return "blocked"
        with self.lock:
            if not self.armed or self.estop_latched:
                reason = "emergency_stop_latched" if self.estop_latched else "not_armed"
                if source == "gesture":
                    self.counters["previewed"] += 1
                    self._record(label, parsed, detection_id, source, "preview", reason, publish_counters=False)
                return "preview"
            if source == "cursor" and isinstance(parsed, MouseMoveAction):
                for queued in self.pending:
                    if queued.source == "cursor" and queued.generation == self.generation:
                        merged_dx = max(-400, min(400, queued.action.dx + parsed.dx))
                        merged_dy = max(-400, min(400, queued.action.dy + parsed.dy))
                        queued.action = MouseMoveAction(dx=merged_dx, dy=merged_dy)
                        self.wakeup.notify_all()
                        return "queued"
            elif source == "gesture":
                for queued in [q for q in self.pending if q.source == "gesture"]:
                    self.pending.remove(queued)
                    self._record(queued.label, queued.action, queued.detection_id, queued.source, "blocked", "superseded")
            request = ActionRequest(
                request_id=uuid.uuid4().hex[:10],
                label=label,
                action=parsed,
                detection_id=detection_id,
                source=source,
                sensor_id=sensor_id,
                generation=self.generation,
                workspace=self.workspace_provider(),
            )
            self.pending.append(request)
            self.wakeup.notify_all()
        return "queued"

    def _executor_loop(self) -> None:
        while not self._stop.is_set():
            with self.wakeup:
                while not self.pending and not self._stop.is_set():
                    self.wakeup.wait(timeout=0.5)
                if self._stop.is_set():
                    return
                request = self.pending.popleft()
            self._execute(request)

    def _gate_inputs(self, request: ActionRequest) -> GateInputs:
        now = time.monotonic()
        control = self.settings.current.control
        session_alive = False
        if self.control_session_id and self.hub.has_client(self.control_session_id):
            heartbeat = self.hub.last_heartbeat(self.control_session_id)
            session_alive = heartbeat is not None and now - heartbeat <= control.heartbeat_timeout_s
        cooldown_ok = True
        if request.source == "gesture":
            last = self.last_action_at.get(request.label)
            cooldown_ok = last is None or now - last >= self.cooldown_provider()
        repeat = request.detection_id is not None and request.detection_id in self.executed_detections
        allowlisted = True
        try:
            parse_any_action(request.action.model_dump())
        except ValidationError:
            allowlisted = False
        activation_ok = True
        if control.sound_activation_required and request.source == "gesture":
            activation_ok = bool(self.activation_check())
        return GateInputs(
            armed=self.armed,
            estop_latched=self.estop_latched,
            generation_matches=request.generation == self.generation,
            session_alive=session_alive,
            sensor_healthy=True if request.sensor_id is None else bool(self.sensor_health(request.sensor_id)),
            allowlisted=allowlisted,
            is_idle_label=False,
            cooldown_ok=cooldown_ok,
            repeat=repeat,
            activation_ok=activation_ok,
            workspace_matches=request.workspace == self.workspace_provider() == self.armed_workspace,
        )

    def _backend(self, workspace: str) -> Any:
        if workspace == "demo":
            return self._sim_backend
        if self._real_backend is None:
            self._real_backend = self.backend_factory()
        return self._real_backend

    def _execute(self, request: ActionRequest) -> None:
        with self.lock:
            allowed, reason = gate_decision(self._gate_inputs(request))
            if not allowed:
                self._record(request.label, request.action, request.detection_id, request.source, "blocked", reason)
                return
            backend = self._backend(request.workspace)
            try:
                backend.execute(request.action)
            except FailSafeTriggered:
                self._record(request.label, request.action, request.detection_id, request.source, "blocked", "pyautogui_failsafe")
                failsafe = True
            except Exception as exc:
                self.counters["errors"] += 1
                self._record(request.label, request.action, request.detection_id, request.source, "error", f"{type(exc).__name__}: {exc}")
                failsafe = None
            else:
                failsafe = False
                now = time.monotonic()
                if request.source == "gesture":
                    self.last_action_at[request.label] = now
                self.last_executed_at = now
                if request.detection_id:
                    self.executed_detections.append(request.detection_id)
                outcome = "simulated" if getattr(backend, "simulated", False) else "executed"
                self.counters[outcome] += 1
                self._record(request.label, request.action, request.detection_id, request.source, outcome, "ok", log=request.source != "cursor")
        if failsafe:
            self.emergency_stop("pyautogui_failsafe")
        elif failsafe is None:
            self.disarm("executor_error")

    def _record(self, label: str, action: BaseModel | None, detection_id: str | None, source: str, outcome: str, reason: str, log: bool = True, publish_counters: bool = True) -> None:
        if outcome == "blocked":
            self.counters["blocked"] += 1
        entry = {
            "at": time.time(),
            "label": label,
            "action": action.model_dump() if action is not None else None,
            "description": describe_action(action) if action is not None else "invalid action",
            "detection_id": detection_id,
            "source": source,
            "outcome": outcome,
            "reason": reason,
            "workspace": self.workspace_provider(),
        }
        if source == "cursor" and outcome in ("executed", "simulated"):
            return
        self.history.append(entry)
        if log and outcome in ("executed", "simulated"):
            verb = "Simulated" if outcome == "simulated" else "Executed"
            self.activity.info("control", f"{verb}: {entry['description']} (gesture {label})", outcome=outcome)
        elif log and outcome in ("blocked", "error") and reason not in ("cooldown", "repeat_detection"):
            self.activity.warning("control", f"Action blocked: {entry['description']} — {reason}", reason=reason)
        self.hub.publish("actions", "action", entry)

    def _monitor_loop(self) -> None:
        while not self._stop.wait(0.25):
            if not self.armed:
                continue
            control = self.settings.current.control
            session = self.control_session_id
            if session is None or not self.hub.has_client(session):
                self.disarm("control_session_closed")
                continue
            heartbeat = self.hub.last_heartbeat(session)
            if heartbeat is None or time.monotonic() - heartbeat > control.heartbeat_timeout_s:
                self.disarm("control_session_heartbeat_lost")
                continue
            if control.auto_disarm_idle_minutes and self.last_executed_at is not None:
                if time.monotonic() - self.last_executed_at > control.auto_disarm_idle_minutes * 60:
                    self.disarm("idle_timeout")

    def on_client_closed(self, client_id: str) -> None:
        if self.armed and client_id == self.control_session_id:
            self.disarm("control_session_closed")

    def on_sensor_event(self, event: str, sensor_id: str, _data: dict) -> None:
        if not self.armed or event not in LOSS_EVENTS:
            return
        monitored = self.monitored_sensors()
        if not monitored or sensor_id in monitored:
            self.disarm(f"sensor_{event}:{sensor_id}")

    def on_settings_changed(self, old: Any, new: Any) -> None:
        if old.demo_mode != new.demo_mode:
            self.disarm("mode_changed")
        if not new.control.pc_control_enabled and self.armed:
            self.disarm("pc_control_disabled")
        self.publish()
