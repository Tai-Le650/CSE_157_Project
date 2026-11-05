from __future__ import annotations

import time

import numpy as np

from app.control.cursor import cursor_velocity
from app.ml.airwriting import dtw_distance, evaluate, preprocess
from app.processing.activation import ActivationStateMachine
from app.sensors.demo_device import GYRO_BIAS
from conftest import wait_for


def test_capabilities_are_honest(api):
    caps = api.get("/api/advanced/capabilities").json()
    assert caps["ble"]["available"] is False and "GATT" in caps["ble"]["reason"]
    assert caps["combined_inference"]["available"] is False
    assert caps["sound_activation"]["available"] is False
    assert "IMU data only" in caps["sound_activation"]["reason"]
    assert caps["cursor"]["verified_on_hardware"] is False


def test_cursor_velocity_mapping():
    assert cursor_velocity(5.0, 0.0, 8.0, 4.0, 1500, False) == 0.0
    assert cursor_velocity(18.0, 0.0, 8.0, 4.0, 1500, False) == 40.0
    assert cursor_velocity(18.0, 0.0, 8.0, 4.0, 1500, True) == -40.0
    assert cursor_velocity(10_000.0, 0.0, 8.0, 4.0, 1500, False) == 1500.0
    assert cursor_velocity(10.5, 2.5, 8.0, 4.0, 1500, False) == 0.0


def test_cursor_calibration_on_still_demo_sensor(api):
    api.enable_demo()
    api.connect_demo("1", rate=100)
    wait_for(lambda: api.get("/api/sensors/DEMO-1").json()["status"] == "streaming")
    result = api.post("/api/advanced/cursor/calibrate", {"sensor_id": "DEMO-1", "seconds": 1.5}).json()
    assert result["calibrated_sensor_id"] == "DEMO-1"
    bias = result["settings"]["bias_dps"]
    assert abs(bias["gx"] - GYRO_BIAS[0]) < 0.4 and abs(bias["gy"] - GYRO_BIAS[1]) < 0.4 and abs(bias["gz"] - GYRO_BIAS[2]) < 0.4
    assert result["verified_on_hardware"] is False
    blocked = api.post("/api/advanced/cursor/start", {"sensor_id": "DEMO-1"})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "not_armed"


def test_two_sensor_sync_measurement_in_demo(api):
    api.enable_demo()
    api.connect_demo("1", rate=100, hand="left")
    api.connect_demo("2", rate=100, hand="right")
    wait_for(lambda: all(api.get(f"/api/sensors/DEMO-{i}").json()["status"] == "streaming" for i in (1, 2)))
    wait_for(lambda: all(a["ready"] for a in api.get("/api/advanced/sync").json()["alignments"].values()), timeout=8)
    gate_before = api.get("/api/advanced/sync/gate?a=DEMO-1&b=DEMO-2").json()
    assert gate_before["combined_inference_allowed"] is False
    response = api.post("/api/advanced/sync/measure", {"sensor_ids": ["DEMO-1", "DEMO-2"], "duration_s": 5, "simulated_taps": 5})
    assert response.status_code == 200, response.text
    wait_for(lambda: not api.get("/api/advanced/sync").json()["measuring"], timeout=15)
    measurement = api.get("/api/advanced/sync").json()["measurements"][0]
    assert measurement["details"]["simulated"] is True
    assert measurement["events_used"] >= 3
    assert measurement["max_abs_error_ms"] < 50
    gate = api.get("/api/advanced/sync/gate?a=DEMO-2&b=DEMO-1").json()
    assert gate["simulated"] is True
    assert gate["latest_measurement"]["measurement_id"] == measurement["measurement_id"]


def test_dual_sensor_trials_share_capture(api):
    api.enable_demo()
    api.connect_demo("1", rate=100, hand="left")
    api.connect_demo("2", rate=100, hand="right")
    wait_for(lambda: all(api.get(f"/api/sensors/DEMO-{i}").json()["status"] == "streaming" for i in (1, 2)))
    api.post("/api/recorder/trials", {"label_id": "swipe_right", "sensor_ids": ["DEMO-1", "DEMO-2"], "duration_s": 1.0, "countdown_s": 0.1, "trials": 1})
    wait_for(lambda: not api.get("/api/recorder").json()["state"]["active"], timeout=10)
    staging = api.get("/api/recorder").json()["staging"]
    assert {s["sensor_id"] for s in staging} == {"DEMO-1", "DEMO-2"}
    assert len({s["capture_id"] for s in staging}) == 1
    assert len({s["recording_id"] for s in staging}) == 2


def test_sound_activation_state_machine():
    machine = ActivationStateMachine(threshold=0.5, active_window_s=1.0, refractory_s=0.2)
    assert machine.update(0.1, 0.0) is None and machine.state == "idle"
    assert machine.update(0.9, 0.1) == "activated" and machine.state == "active"
    assert machine.update(0.9, 0.2) is None
    assert machine.update(0.1, 1.05) is None and machine.state == "active"
    assert machine.update(0.1, 1.2) == "timeout" and machine.state == "idle"
    assert machine.update(0.95, 1.5) == "activated"


def test_sound_activation_demo_and_real_gate(api):
    api.patch("/api/settings", {"values": {"control": {"pc_control_enabled": True, "sound_activation_required": True}}})
    with api.ws() as ws:
        client = ws.receive_json()["data"]["client_id"]
        reasons = api.post("/api/control/arm", {"control_session_id": client, "confirm": True}).json()["error"]["details"]["reasons"]
    assert any("Sound activation is required" in r for r in reasons)
    assert api.post("/api/advanced/sound/demo/start").status_code == 409
    api.enable_demo()
    api.patch("/api/settings", {"values": {"sound": {"active_window_s": 1.0, "threshold": 0.5}}})
    started = api.post("/api/advanced/sound/demo/start").json()
    assert started["available"] is True and started["simulated"] is True
    api.post("/api/advanced/sound/demo/clap")
    wait_for(lambda: api.get("/api/advanced/sound").json()["state"] == "active", timeout=3)
    wait_for(lambda: api.get("/api/advanced/sound").json()["state"] == "idle", timeout=4)
    api.post("/api/advanced/sound/demo/stop")


def test_dtw_air_writing_baseline():
    t = np.linspace(0, 1, 60) * 1e6
    def stroke(kind, warp=1.0, noise=0.0, seed=0):
        rng = np.random.default_rng(seed)
        u = (np.linspace(0, 1, 60) ** warp)
        v = np.zeros((60, 6))
        if kind == "a":
            v[:, 3] = np.sin(2 * np.pi * u)
            v[:, 5] = np.cos(2 * np.pi * u)
        else:
            v[:, 4] = np.sign(np.sin(3 * np.pi * u))
            v[:, 5] = u
        return v + rng.normal(0, noise, v.shape)
    a1 = preprocess(t, stroke("a"))
    a2 = preprocess(t, stroke("a", warp=1.3))
    b1 = preprocess(t, stroke("b"))
    assert dtw_distance(a1, a1) == 0.0
    assert dtw_distance(a1, a2) < dtw_distance(a1, b1)
    templates = np.stack([preprocess(t, stroke(k, warp=w, noise=0.05, seed=i)) for i, (k, w) in enumerate([("a", 1.0), ("a", 1.2), ("b", 1.0), ("b", 1.2)] * 2)])
    labels = ["char_a", "char_a", "char_b", "char_b"] * 2
    groups = ["s1"] * 4 + ["s2"] * 4
    result = evaluate(templates, labels, groups)
    assert result["status"] == "evaluated" and result["accuracy"] == 1.0
    assert evaluate(templates[:4], labels[:4], groups[:4])["status"] == "insufficient_grouped_data"


def test_performance_endpoint(api):
    first = api.get("/api/advanced/performance").json()
    time.sleep(0.3)
    second = api.get("/api/advanced/performance").json()
    assert second["process_cpu_percent_since_last_call"] is not None
    assert second["threads"] >= 1
    assert "end-to-end" in first["note"]
