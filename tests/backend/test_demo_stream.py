from __future__ import annotations

from conftest import receive_until, wait_for


def test_simulated_sensor_requires_demo_mode(api):
    response = api.post("/api/sensors", {"sensor_id": "1", "simulated": True})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "simulated_requires_demo_mode"


def test_demo_mode_blocks_real_ports(api):
    api.enable_demo()
    response = api.post("/api/sensors", {"sensor_id": "S1", "port": "COM99"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "demo_mode_blocks_real_ports"


def test_demo_sensor_streams_labeled_samples(api):
    api.enable_demo()
    sensor = api.connect_demo("1", rate=100)
    assert sensor["sensor_id"] == "DEMO-1"
    assert sensor["simulated"] is True
    assert sensor["port"] == "demo://DEMO-1"
    with api.ws() as ws:
        ws.receive_json()
        ws.send_json({"type": "subscribe", "topics": ["samples:DEMO-1", "connections"]})
        batch = receive_until(ws, lambda m: m["type"] == "samples")
        assert batch["data"]["simulated"] is True
        assert batch["data"]["sensor_id"] == "DEMO-1"
        assert len(batch["data"]["t_us"]) == len(batch["data"]["gz"]) > 0
        assert abs(batch["data"]["az"][0] - 0.99) < 0.1
    state = wait_for(lambda: (s := api.get("/api/sensors/DEMO-1").json())["status"] == "streaming" and s["rates"]["device_hz"] and s)
    assert 85 < state["rates"]["device_hz"] < 115
    assert state["header_alias"] == "t_us"
    assert state["counters"]["malformed_total"] == 0
    status = api.get("/api/status").json()
    assert status["modes"]["demo"] is True
    assert status["modes"]["monitoring"] is True


def test_demo_perform_and_disconnect(api):
    api.enable_demo()
    api.connect_demo("2")
    assert api.post("/api/demo/sensors/DEMO-2/perform", {"label": "swipe_left"}).status_code == 200
    assert api.post("/api/demo/sensors/DEMO-2/perform", {"label": "rocket"}).status_code == 422
    wait_for(lambda: len(api.get("/api/demo/sensors/DEMO-2/history").json()) == 1)
    response = api.post("/api/sensors/DEMO-2/disconnect")
    assert response.json()["status"] == "disconnected"
    assert api.get("/api/status").json()["modes"]["monitoring"] is False


def test_switching_modes_disconnects_sensors(api):
    api.enable_demo()
    api.connect_demo("3")
    response = api.post("/api/settings/demo-mode", {"enabled": False, "confirm": True})
    assert response.status_code == 200
    assert api.get("/api/sensors").json() == []
    assert api.get("/api/status").json()["workspace"] == "real"
