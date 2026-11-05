from __future__ import annotations

import pytest
import serial
from fastapi.testclient import TestClient

from conftest import BASE_URL, Api, wait_for

DT = 9615


class LoopPorts:
    def __init__(self):
        self.ports = {}

    def __call__(self, port: str, baud: int):
        if port == "COM_BUSY":
            raise serial.SerialException("could not open port 'COM_BUSY': PermissionError(13, 'Access is denied.', None, 5)")
        if port == "COM_GONE":
            raise serial.SerialException("could not open port 'COM_GONE': FileNotFoundError(2, 'The system cannot find the file specified.', None, 2)")
        handle = serial.serial_for_url("loop://", timeout=0.05)
        self.ports[port] = handle
        return handle


def lines(start=1_000_000, n=200, glitch_at=None, gap_at=None):
    out = []
    t = start
    for i in range(n):
        if gap_at is not None and i == gap_at:
            t += DT
        stamp = str(t)
        if glitch_at is not None and i == glitch_at:
            stamp = stamp[3:]
        out.append(f"{stamp},0.010,-0.020,0.990,0.50,-1.10,0.30\n")
        t += DT
    return "".join(out).encode()


@pytest.fixture
def loop_api(app_factory):
    ports = LoopPorts()
    app = app_factory(serial_opener=ports)
    with TestClient(app, base_url=BASE_URL) as client:
        api = Api(client)
        api.ports = ports
        yield api


def connect(api, sensor_id="S1", port="COM7"):
    response = api.post("/api/sensors", {"sensor_id": sensor_id, "port": port, "hand": "left"})
    assert response.status_code == 201, response.text
    wait_for(lambda: port in api.ports.ports)
    return api.ports.ports[port]


def test_real_stream_counts_and_rates(loop_api):
    port = connect(loop_api)
    port.write(b"t_us,ax,ay,az,gx,gy,gz\n" + lines(n=300, glitch_at=120, gap_at=200) + b"12,1,2\nIMU initialized!\n" + lines(start=1_000_000 + 301 * DT, n=50))
    state = wait_for(lambda: (s := loop_api.get("/api/sensors/S1").json())["timing"].get("decided", 0) >= 349 and s)
    assert state["status"] == "streaming"
    assert state["hand"] == "left"
    assert state["header_alias"] == "t_us"
    assert state["column_order_assumed"] is False
    assert state["counters"]["samples_parsed"] == 350
    assert state["counters"]["malformed"] == {"field_count": 1}
    assert state["counters"]["diagnostics"] == 1
    assert state["timing"]["glitches"] == 1
    assert state["timing"]["gaps"] == 1
    assert state["timing"]["estimated_missing"] == 1
    assert state["timing"]["resets"] == 0
    assert abs(state["timing"]["median_interval_hz"] - 1e6 / DT) < 0.5


def test_one_owner_per_port_and_unique_ids(loop_api):
    connect(loop_api, "S1", "COM7")
    second = loop_api.post("/api/sensors", {"sensor_id": "S2", "port": "COM7"})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "port_owned"
    same_id = loop_api.post("/api/sensors", {"sensor_id": "S1", "port": "COM8"})
    assert same_id.status_code == 409
    assert same_id.json()["error"]["code"] == "sensor_id_in_use"
    ports = loop_api.get("/api/ports").json()
    assert isinstance(ports, list)


def test_port_in_use_and_missing_are_reported(loop_api):
    loop_api.post("/api/sensors", {"sensor_id": "B1", "port": "COM_BUSY"})
    busy = wait_for(lambda: (s := loop_api.get("/api/sensors/B1").json())["status"] == "error" and s)
    assert busy["error"]["code"] == "port_in_use"
    assert "Serial Monitor" in busy["error"]["hint"]
    loop_api.post("/api/sensors", {"sensor_id": "G1", "port": "COM_GONE"})
    gone = wait_for(lambda: (s := loop_api.get("/api/sensors/G1").json())["status"] == "error" and s)
    assert gone["error"]["code"] == "port_not_found"


def test_unplug_is_detected_and_reconnect_works(loop_api):
    events = []
    loop_api.container.sensors.add_listener(lambda event, sid, data: events.append((event, sid)))
    port = connect(loop_api)
    port.write(b"t_us,ax,ay,az,gx,gy,gz\n" + lines(n=50))
    wait_for(lambda: loop_api.get("/api/sensors/S1").json()["status"] == "streaming")
    port.close()
    lost = wait_for(lambda: (s := loop_api.get("/api/sensors/S1").json())["status"] == "disconnected" and s)
    assert lost["totals"]["disconnects"] == 1
    assert ("lost", "S1") in events
    response = loop_api.post("/api/sensors/S1/reconnect")
    assert response.status_code == 200
    port2 = wait_for(lambda: (p := loop_api.ports.ports.get("COM7")) is not port and p)
    port2.write(b"t_us,ax,ay,az,gx,gy,gz\n" + lines(n=30))
    wait_for(lambda: loop_api.get("/api/sensors/S1").json()["status"] == "streaming")


def test_stall_and_recovery(loop_api):
    loop_api.patch("/api/settings", {"values": {"acquisition": {"stall_timeout_s": 0.3}}})
    events = []
    loop_api.container.sensors.add_listener(lambda event, sid, data: events.append(event))
    port = connect(loop_api)
    port.write(b"t_us,ax,ay,az,gx,gy,gz\n" + lines(n=40))
    wait_for(lambda: loop_api.get("/api/sensors/S1").json()["status"] == "streaming")
    wait_for(lambda: loop_api.get("/api/sensors/S1").json()["status"] == "stalled", timeout=3)
    port.write(lines(start=1_000_000 + 40 * DT, n=20))
    wait_for(lambda: loop_api.get("/api/sensors/S1").json()["status"] == "streaming")
    assert "stalled" in events and "recovered" in events


def test_identity_changes(loop_api):
    connect(loop_api)
    assert loop_api.patch("/api/sensors/S1", {"hand": "right"}).json()["hand"] == "right"
    rename_live = loop_api.patch("/api/sensors/S1", {"sensor_id": "LEFT1"})
    assert rename_live.status_code == 409
    loop_api.post("/api/sensors/S1/disconnect")
    renamed = loop_api.patch("/api/sensors/S1", {"sensor_id": "LEFT1"})
    assert renamed.status_code == 200
    assert renamed.json()["sensor_id"] == "LEFT1"
    assert loop_api.post("/api/sensors", {"sensor_id": "DEMO-X", "port": "COM9"}).status_code == 422


def test_buffer_export_csv(loop_api):
    port = connect(loop_api)
    port.write(b"t_us,ax,ay,az,gx,gy,gz\n" + lines(n=120))
    wait_for(lambda: loop_api.get("/api/sensors/S1").json()["totals"]["valid_samples"] >= 119)
    response = loop_api.get("/api/sensors/S1/buffer?seconds=5&fmt=csv")
    assert response.status_code == 200
    rows = response.text.strip().splitlines()
    assert rows[0] == "t_us,ax,ay,az,gx,gy,gz,host_rx_ns"
    assert len(rows) >= 100
