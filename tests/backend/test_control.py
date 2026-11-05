from __future__ import annotations

import time
import pytest
from pydantic import ValidationError

from app.control.actions import HotkeyAction, KeyAction, describe_action, parse_gesture_action
from app.control.executor import RecordingFakeBackend
from app.control.gate import GateInputs, gate_decision
from app.control.service import ControlService
from app.settings.service import AppSettings
from conftest import receive_until, wait_for


class FakeHub:
    def __init__(self):
        self.clients = {"tab1": time.monotonic()}
        self.messages = []

    def has_client(self, cid):
        return cid in self.clients

    def last_heartbeat(self, cid):
        return self.clients.get(cid)

    def publish(self, topic, type_, data):
        self.messages.append((topic, type_, data))


class FakeActivity:
    def __init__(self):
        self.entries = []

    def info(self, *a, **k):
        self.entries.append(("info", a))

    def warning(self, *a, **k):
        self.entries.append(("warning", a))

    def error(self, *a, **k):
        self.entries.append(("error", a))


class FakeSettings:
    def __init__(self, enabled=True, cooldown=0.5, heartbeat=3.0):
        base = AppSettings().model_dump()
        base["control"]["pc_control_enabled"] = enabled
        base["control"]["heartbeat_timeout_s"] = heartbeat
        base["inference"]["cooldown_s"] = cooldown
        self.current = AppSettings.model_validate(base)


def make_service(workspace="real", enabled=True, cooldown=0.5, heartbeat=3.0, factory=None):
    hub = FakeHub()
    backend = RecordingFakeBackend()
    svc = ControlService(hub, FakeActivity(), FakeSettings(enabled, cooldown, heartbeat), lambda: workspace, backend_factory=factory or (lambda: backend), enable_global_hotkey=False)
    svc.start()
    return svc, hub, backend


def gate(**overrides):
    base = dict(armed=True, estop_latched=False, generation_matches=True, session_alive=True, sensor_healthy=True, allowlisted=True, is_idle_label=False, cooldown_ok=True, repeat=False, activation_ok=True, workspace_matches=True)
    base.update(overrides)
    return gate_decision(GateInputs(**base))


def test_gate_blocks_each_condition():
    assert gate() == (True, "ok")
    assert gate(estop_latched=True)[1] == "emergency_stop_latched"
    assert gate(armed=False)[1] == "not_armed"
    assert gate(generation_matches=False)[1] == "stale_request"
    assert gate(session_alive=False)[1] == "control_session_lost"
    assert gate(sensor_healthy=False)[1] == "sensor_unhealthy"
    assert gate(allowlisted=False)[1] == "action_not_allowlisted"
    assert gate(is_idle_label=True)[1] == "idle_never_acts"
    assert gate(repeat=True)[1] == "repeat_detection"
    assert gate(cooldown_ok=False)[1] == "cooldown"
    assert gate(workspace_matches=False)[1] == "workspace_changed"


def test_allowlist_rejects_unsafe_actions():
    assert isinstance(parse_gesture_action({"type": "key", "key": "left"}), KeyAction)
    assert describe_action(HotkeyAction(modifiers=["shift", "ctrl"], key="tab")) == "Press Ctrl+Shift+Tab"
    for bad in (
        {"type": "key", "key": "win"},
        {"type": "key", "key": "delete"},
        {"type": "hotkey", "modifiers": ["alt"], "key": "f4"},
        {"type": "hotkey", "modifiers": ["ctrl", "shift"], "key": "esc"},
        {"type": "hotkey", "modifiers": ["win"], "key": "r"},
        {"type": "type_text", "text": "rm -rf"},
        {"type": "run", "command": "calc.exe"},
        {"type": "scroll", "notches": 0},
        {"type": "mouse_move", "dx": 5, "dy": 5},
    ):
        with pytest.raises(ValidationError):
            parse_gesture_action(bad)


def test_disarmed_service_never_executes():
    svc, _hub, backend = make_service()
    assert svc.submit("swipe_left", {"type": "key", "key": "left"}, "d1") == "preview"
    time.sleep(0.2)
    assert len(backend.calls) == 0
    svc.stop()


def test_armed_execution_cooldown_repeat_and_estop():
    svc, _hub, backend = make_service(cooldown=0.5)
    svc.arm("tab1", True)
    assert svc.submit("swipe_left", {"type": "key", "key": "left"}, "d1", sensor_id=None) == "queued"
    wait_for(lambda: len(backend.calls) == 1)
    svc.submit("swipe_left", {"type": "key", "key": "left"}, "d2")
    time.sleep(0.2)
    assert len(backend.calls) == 1
    assert svc.history[-1]["reason"] == "cooldown"
    time.sleep(0.55)
    svc.submit("swipe_left", {"type": "key", "key": "left"}, "d1")
    time.sleep(0.2)
    assert len(backend.calls) == 1
    assert svc.history[-1]["reason"] == "repeat_detection"
    svc.emergency_stop("test")
    assert svc.armed is False and svc.estop_latched
    assert svc.submit("swipe_right", {"type": "key", "key": "right"}, "d3") == "preview"
    with pytest.raises(Exception):
        svc.arm("tab1", True)
    svc.reset_estop()
    assert svc.armed is False
    svc.stop()


def test_estop_clears_pending_actions():
    svc, _hub, backend = make_service()
    svc.arm("tab1", True)
    with svc.lock:
        svc.submit("swipe_left", {"type": "key", "key": "left"}, "p1")
        assert len(svc.pending) == 1
        svc.emergency_stop("test")
        assert len(svc.pending) == 0
    time.sleep(0.2)
    assert len(backend.calls) == 0
    svc.stop()


def test_idle_never_acts_even_when_armed():
    svc, _hub, backend = make_service()
    svc.arm("tab1", True)
    assert svc.submit("idle", {"type": "key", "key": "space"}, "i1", is_idle=True) == "blocked"
    time.sleep(0.2)
    assert len(backend.calls) == 0
    svc.stop()


def test_session_loss_and_hardware_loss_disarm():
    svc, hub, _backend = make_service(heartbeat=1.0)
    svc.arm("tab1", True)
    hub.clients["tab1"] = time.monotonic() - 5
    wait_for(lambda: not svc.armed, timeout=2)
    assert svc.last_disarm_reason == "control_session_heartbeat_lost"
    hub.clients["tab1"] = time.monotonic()
    svc.arm("tab1", True)
    svc.on_client_closed("tab1")
    assert not svc.armed and svc.last_disarm_reason == "control_session_closed"
    svc.arm("tab1", True)
    svc.monitored_sensors = lambda: {"S1"}
    svc.on_sensor_event("stalled", "S2", {})
    assert svc.armed
    svc.on_sensor_event("lost", "S1", {})
    assert not svc.armed and svc.last_disarm_reason.startswith("sensor_lost")
    svc.stop()


def test_stale_request_dropped_after_rearm():
    from app.control.service import ActionRequest

    svc, _hub, backend = make_service()
    svc.arm("tab1", True)
    old_generation = svc.generation
    svc.disarm("user")
    svc.arm("tab1", True)
    stale = ActionRequest("r1", "swipe_left", KeyAction(key="left"), "s1", "gesture", None, old_generation, "real")
    with svc.wakeup:
        svc.pending.append(stale)
        svc.wakeup.notify_all()
    wait_for(lambda: svc.history and svc.history[-1]["reason"] == "stale_request")
    assert len(backend.calls) == 0
    svc.stop()


def test_demo_mode_never_builds_real_backend():
    def forbidden():
        raise AssertionError("real OS backend must not be constructed in Demo Mode")

    svc, _hub, _backend = make_service(workspace="demo", factory=forbidden)
    svc.arm("tab1", True)
    svc.submit("swipe_left", {"type": "hotkey", "modifiers": ["ctrl"], "key": "tab"}, "x1")
    wait_for(lambda: svc.counters["simulated"] == 1)
    assert svc.counters["executed"] == 0
    assert svc.history[-1]["outcome"] == "simulated"
    svc.stop()


def test_disabled_by_default_and_prerequisites_reported(api):
    with api.ws() as ws:
        client_id = ws.receive_json()["data"]["client_id"]
        response = api.post("/api/control/arm", {"control_session_id": client_id, "confirm": True})
        assert response.status_code == 409
        reasons = response.json()["error"]["details"]["reasons"]
        assert any("disabled in Settings" in r for r in reasons)
        assert any("Live Recognition" in r for r in reasons)
        api.patch("/api/settings", {"values": {"control": {"pc_control_enabled": True}}})
        response = api.post("/api/control/arm", {"control_session_id": client_id, "confirm": False})
        reasons = response.json()["error"]["details"]["reasons"]
        assert any("confirmation" in r for r in reasons)
        assert not any("disabled in Settings" in r for r in reasons)
    state = api.get("/api/control").json()
    assert state["armed"] is False and state["pc_control_enabled"] is True


def test_setting_and_mode_changes_republish_control_state(api):
    with api.ws() as ws:
        ws.receive_json()
        ws.send_json({"type": "subscribe", "topics": ["status"]})
        receive_until(ws, lambda m: m["type"] == "subscribed")
        api.patch("/api/settings", {"values": {"control": {"pc_control_enabled": True}}})
        allowed = receive_until(ws, lambda m: m["type"] == "control" and m["data"]["pc_control_enabled"] is True)
        assert allowed["data"]["simulated_actions"] is False
        api.post("/api/settings/demo-mode", {"enabled": True, "confirm": True})
        demo = receive_until(ws, lambda m: m["type"] == "control" and m["data"]["simulated_actions"] is True)
        assert demo["data"]["workspace"] == "demo"
        assert demo["data"]["armed"] is False


def test_websocket_estop_latches(api):
    with api.ws() as ws:
        ws.receive_json()
        ws.send_json({"type": "estop"})
        wait_for(lambda: api.get("/api/control").json()["estop_latched"])
    assert api.get("/api/status").json()["estop_latched"] is True
    api.post("/api/control/reset")
    assert api.get("/api/control").json()["estop_latched"] is False


def test_mapping_profiles_and_simulation(api):
    profiles = {p["profile_id"]: p for p in api.get("/api/mappings/profiles").json()}
    legacy = profiles["legacy-cli"]
    assert legacy["read_only"] is True
    assert {m["label_id"]: m["action"] for m in legacy["mappings"]} == {"flick_up": {"type": "key", "key": "space"}, "swipe_left": {"type": "key", "key": "left"}, "swipe_right": {"type": "key", "key": "right"}}
    browser = profiles["browser-navigation"]
    assert browser["active"] is True
    assert all(m["enabled"] is False for m in browser["mappings"])
    assert api.put("/api/mappings/profiles/legacy-cli/labels/swipe_left", {"action": {"type": "key", "key": "up"}, "enabled": True}).status_code == 409
    assert api.put("/api/mappings/profiles/browser-navigation/labels/idle", {"action": {"type": "key", "key": "up"}, "enabled": True}).status_code == 422
    assert api.put("/api/mappings/profiles/browser-navigation/labels/swipe_left", {"action": {"type": "key", "key": "win"}, "enabled": True}).status_code == 422
    copy = api.post("/api/mappings/profiles", {"name": "mine", "copy_from": "legacy-cli"}).json()
    assert len(copy["mappings"]) == 3 and all(not m["enabled"] for m in copy["mappings"])
    simulated = api.post("/api/mappings/simulate", {"action": {"type": "scroll", "notches": -3}}).json()
    assert simulated == {"label_id": None, "mapped": True, "action": {"type": "scroll", "notches": -3}, "description": "Would scroll down 3 notches", "executed": False, "simulated": True}
    unmapped = api.post("/api/mappings/simulate", {"label_id": "swipe_left"}).json()
    assert unmapped["mapped"] is False
