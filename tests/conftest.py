from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.main import create_app
from app.settings.config import AppConfig
from app.settings.paths import AppPaths

BASE_URL = "http://127.0.0.1:8000"
ORIGIN = "http://127.0.0.1:5173"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
REFERENCE_RECORDINGS = ROOT.parent / "imu_capture" / "recordings"


def wait_for(predicate, timeout: float = 5.0, interval: float = 0.02):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"Condition not met within {timeout} s (last value: {last!r})")


def build_config(base: Path, **overrides) -> AppConfig:
    paths = AppPaths.for_tests(base, reference_root=overrides.pop("reference_root", None))
    options = dict(
        paths=paths,
        enable_os_control=False,
        enable_global_hotkey=False,
        serve_frontend=False,
        log_to_file=False,
        health_interval_s=0.1,
        ui_flush_interval_s=0.02,
    )
    options.update(overrides)
    return AppConfig(**options)


class Api:
    def __init__(self, client: TestClient):
        self.client = client
        self.token = client.get("/api/session").json()["token"]
        self.headers = {"x-session-token": self.token}

    @property
    def container(self):
        return self.client.app.state.container

    def get(self, path, **kw):
        return self.client.get(path, **kw)

    def post(self, path, json=None, **kw):
        return self.client.post(path, json=json, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def put(self, path, json=None, **kw):
        return self.client.put(path, json=json, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def patch(self, path, json=None, **kw):
        return self.client.patch(path, json=json, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def delete(self, path, **kw):
        return self.client.delete(path, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def ws(self, origin: str | None = ORIGIN):
        headers = {"origin": origin} if origin else {}
        return self.client.websocket_connect(f"ws://127.0.0.1:8000/ws?token={self.token}", headers=headers)

    def enable_demo(self):
        response = self.post("/api/settings/demo-mode", {"enabled": True, "confirm": True})
        assert response.status_code == 200, response.text
        return response.json()

    def connect_demo(self, sensor_id="1", rate=100.0, auto=False, hand="right"):
        response = self.post("/api/sensors", {"sensor_id": sensor_id, "simulated": True, "demo_rate_hz": rate, "demo_auto": auto, "hand": hand})
        assert response.status_code == 201, response.text
        return response.json()


@pytest.fixture
def config_factory(tmp_path):
    def factory(**overrides):
        return build_config(tmp_path, **overrides)

    return factory


@pytest.fixture
def app_factory(config_factory):
    def factory(**overrides):
        return create_app(config_factory(**overrides))

    return factory


@pytest.fixture
def api(app_factory):
    app = app_factory()
    with TestClient(app, base_url=BASE_URL) as client:
        yield Api(client)


def receive_until(ws, predicate, limit: int = 400):
    for _ in range(limit):
        message = ws.receive_json()
        if predicate(message):
            return message
    raise AssertionError("Expected WebSocket message not received")
