from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.deps import get_container
from app.main import create_app
from app.settings.config import AppConfig, HostedLimits, hosted_config
from app.settings.paths import AppPaths
from conftest import wait_for

HOST = "testserver"
ORIGIN = f"http://{HOST}"
STATELESS_GETS = {"/api/health", "/api/training/features", "/api/control/allowlist", "/api/mappings/allowlist", "/api/advanced/sound/requirements"}


def make_hosted_app(tmp_path: Path, **limits):
    config = hosted_config(
        AppPaths.isolated(tmp_path / "app"),
        serve_frontend=False,
        sandbox_root=tmp_path / "sandboxes",
        hosted_limits=HostedLimits(**limits),
        health_interval_s=0.1,
        ui_flush_interval_s=0.02,
    )
    return create_app(config)


class Visitor:
    def __init__(self, client: TestClient, token: str | None = None):
        self.client = client
        response = client.get("/api/session", headers={"x-session-token": token} if token else {})
        assert response.status_code == 200, response.text
        self.session = response.json()
        self.token = self.session["token"]
        self.headers = {"x-session-token": self.token}

    @property
    def sandbox(self):
        return self.client.app.state.sandboxes.lookup(self.token)

    def get(self, path):
        return self.client.get(path, headers=self.headers)

    def post(self, path, json=None):
        return self.client.post(path, json=json if json is not None else {}, headers=self.headers)

    def put(self, path, json=None):
        return self.client.put(path, json=json if json is not None else {}, headers=self.headers)

    def ws(self, origin: str | None = ORIGIN):
        return self.client.websocket_connect(f"ws://{HOST}/ws?token={self.token}", headers={"origin": origin} if origin else {})


def error_code(response) -> str:
    return response.json()["error"]["code"]


@pytest.fixture
def hosted(tmp_path):
    def factory(**limits):
        return TestClient(make_hosted_app(tmp_path, **limits))

    return factory


def test_each_visitor_gets_a_private_demo_sandbox(hosted):
    with hosted() as client:
        a, b = Visitor(client), Visitor(client)
        assert a.token != b.token
        assert a.session["hosted"] is True
        assert a.session["limits"]["max_sandboxes"] == HostedLimits().max_sandboxes
        for visitor in (a, b):
            assert visitor.get("/api/settings").json()["demo_mode"] is True
            assert visitor.get("/api/status").json()["workspace"] == "demo"
        created = a.post("/api/labels", {"label_id": "only_a", "display_name": "Only A"})
        assert created.status_code in (200, 201), created.text
        assert "only_a" in {label["label_id"] for label in a.get("/api/labels").json()}
        assert "only_a" not in {label["label_id"] for label in b.get("/api/labels").json()}
        assert a.sandbox.base_dir != b.sandbox.base_dir
        assert a.sandbox.base_dir.is_dir() and b.sandbox.base_dir.is_dir()


def test_a_live_token_resumes_its_sandbox_and_a_stale_one_gets_a_new_sandbox(hosted):
    with hosted() as client:
        a = Visitor(client)
        assert Visitor(client, a.token).token == a.token
        assert len(client.app.state.sandboxes) == 1
        assert Visitor(client, "expired-token").token != a.token
        assert len(client.app.state.sandboxes) == 2


def test_requests_without_a_live_sandbox_token_are_rejected(hosted):
    with hosted() as client:
        Visitor(client)
        assert client.get("/api/health").status_code == 200
        for headers in ({}, {"x-session-token": "nope"}):
            response = client.get("/api/status", headers=headers)
            assert response.status_code == 401
            assert error_code(response) == "invalid_session_token"
        assert client.post("/api/control/disarm", json={"reason": "x"}, headers={"x-session-token": "nope"}).status_code == 401
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect(f"ws://{HOST}/ws?token=nope", headers={"origin": ORIGIN}) as ws:
                ws.receive_json()
        assert closed.value.code == 1008


def test_only_same_origin_requests_are_accepted(hosted):
    with hosted() as client:
        a = Visitor(client)
        evil = client.get("/api/status", headers={**a.headers, "origin": "http://evil.example"})
        assert evil.status_code == 403
        assert error_code(evil) == "origin_rejected"
        assert client.get("/api/status", headers={**a.headers, "origin": ORIGIN}).status_code == 200
        assert client.get("/api/status", headers={**a.headers, "sec-fetch-site": "cross-site"}).status_code == 403
        with pytest.raises(WebSocketDisconnect) as closed:
            with a.ws(origin="http://evil.example") as ws:
                ws.receive_json()
        assert closed.value.code == 1008
        with a.ws() as ws:
            hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["data"]["snapshot"]["status"]["workspace"] == "demo"


def test_local_only_features_are_refused_online(hosted):
    with hosted() as client:
        a = Visitor(client)
        for response in (
            a.post("/api/settings/demo-mode", {"enabled": False, "confirm": True}),
            a.put("/api/settings/storage", {"data_dir": str(Path.home())}),
            a.post("/api/models/any/trust", {"confirm": True}),
        ):
            assert response.status_code == 403, response.text
            assert error_code(response) == "not_available_online"
        assert a.get("/api/ports").json() == []
        real = a.post("/api/sensors", {"sensor_id": "board", "port": "COM5"})
        assert real.status_code == 409
        assert error_code(real) == "demo_mode_blocks_real_ports"
        fast = a.post("/api/sensors", {"sensor_id": "1", "simulated": True, "demo_rate_hz": 400})
        assert fast.status_code == 422
        assert error_code(fast) == "rate_limit_online"
        assert a.get("/api/settings").json()["demo_mode"] is True


def test_a_sandbox_streams_a_simulated_sensor_and_caps_the_sensor_count(hosted):
    with hosted(max_sensors=1) as client:
        a = Visitor(client)
        first = a.post("/api/sensors", {"sensor_id": "1", "simulated": True, "demo_rate_hz": 100})
        assert first.status_code == 201, first.text
        sensor_id = first.json()["sensor_id"]
        wait_for(lambda: a.get(f"/api/sensors/{sensor_id}").json()["status"] == "streaming", timeout=10)
        second = a.post("/api/sensors", {"sensor_id": "2", "simulated": True})
        assert second.status_code == 409
        assert error_code(second) == "sensor_limit_online"


def test_new_sandboxes_start_with_recognition_settings_sized_for_the_server(hosted):
    with hosted(min_hop_s=0.25, default_threshold=0.7, default_smoothing_k=1, default_debounce_n=1) as client:
        inference = Visitor(client).get("/api/settings").json()["inference"]
        assert (inference["hop_s"], inference["threshold"], inference["smoothing_k"], inference["debounce_n"]) == (0.25, 0.7, 1, 1)


def test_streaming_sensors_are_capped_across_all_visitors(hosted):
    with hosted(max_streaming_sensors=1) as client:
        a, b = Visitor(client), Visitor(client)
        first = a.post("/api/sensors", {"sensor_id": "1", "simulated": True})
        assert first.status_code == 201, first.text
        busy = b.post("/api/sensors", {"sensor_id": "1", "simulated": True})
        assert busy.status_code == 409
        assert error_code(busy) == "server_busy_sensors"
        assert a.post(f"/api/sensors/{first.json()['sensor_id']}/disconnect").status_code == 200
        assert b.post("/api/sensors", {"sensor_id": "1", "simulated": True}).status_code == 201


def test_sensors_pause_after_a_minute_without_an_open_tab(hosted):
    with hosted() as client:
        registry = client.app.state.sandboxes
        away, watching = Visitor(client), Visitor(client)
        sensor = {}
        for visitor in (away, watching):
            response = visitor.post("/api/sensors", {"sensor_id": "1", "simulated": True})
            assert response.status_code == 201, response.text
            sensor[visitor.token] = response.json()["sensor_id"]
            wait_for(lambda v=visitor: v.get(f"/api/sensors/{sensor[v.token]}").json()["status"] == "streaming", timeout=10)
        with watching.ws() as ws:
            assert ws.receive_json()["type"] == "hello"
            assert client.portal.call(registry.reap, time.monotonic() + 30) == []
            assert away.get(f"/api/sensors/{sensor[away.token]}").json()["status"] == "streaming"
            assert client.portal.call(registry.reap, time.monotonic() + 61) == []
            assert away.get(f"/api/sensors/{sensor[away.token]}").json()["status"] == "disconnected"
            assert watching.get(f"/api/sensors/{sensor[watching.token]}").json()["status"] == "streaming"
            assert away.sandbox is not None


def test_sandbox_count_is_capped_overall_and_per_network(hosted):
    with hosted(max_sandboxes=2, max_sandboxes_per_ip=5) as client:
        Visitor(client)
        Visitor(client)
        full = client.get("/api/session")
        assert full.status_code == 503
        assert error_code(full) == "demo_full"
    with hosted(max_sandboxes=5, max_sandboxes_per_ip=1) as client:
        Visitor(client)
        busy = client.get("/api/session")
        assert busy.status_code == 429
        assert error_code(busy) == "too_many_sandboxes"


def test_idle_sandboxes_are_closed_and_their_files_deleted(hosted):
    with hosted(idle_minutes=1, max_age_minutes=5) as client:
        registry = client.app.state.sandboxes
        a = Visitor(client)
        sandbox = a.sandbox
        assert client.portal.call(registry.reap, time.monotonic() + 30) == []
        assert client.portal.call(registry.reap, time.monotonic() + 61) == [sandbox.sandbox_id]
        assert not sandbox.base_dir.exists()
        assert a.get("/api/status").status_code == 401


def test_an_open_tab_keeps_its_sandbox_until_the_maximum_age(hosted):
    with hosted(idle_minutes=1, max_age_minutes=5) as client:
        registry = client.app.state.sandboxes
        a = Visitor(client)
        sandbox_id = a.sandbox.sandbox_id
        reaped: list[list[str]] = []
        with pytest.raises(WebSocketDisconnect) as closed:
            with a.ws() as ws:
                assert ws.receive_json()["type"] == "hello"
                reaped.append(client.portal.call(registry.reap, time.monotonic() + 120))
                reaped.append(client.portal.call(registry.reap, time.monotonic() + 301))
                ws.receive_json()
        assert closed.value.code == 1008
        assert reaped == [[], [sandbox_id]]


def test_training_runs_one_job_at_a_time_with_capped_settings(hosted):
    with hosted(max_trees=50, max_folds=3) as client:
        a, b = Visitor(client), Visitor(client)
        captured = []
        b.sandbox.container.training.start = lambda config: captured.append(config) or {"job_id": "job-b", "status": "running"}
        body = {"dataset_id": "ds", "n_estimators": 500, "n_splits_max": 8, "n_jobs": 4}
        a.sandbox.container.training.active_job_id = "job-a"
        try:
            busy = b.post("/api/training/jobs", body)
            assert busy.status_code == 409
            assert error_code(busy) == "server_busy"
        finally:
            a.sandbox.container.training.active_job_id = None
        started = b.post("/api/training/jobs", body)
        assert started.status_code == 201, started.text
        assert (captured[0].n_estimators, captured[0].n_splits_max, captured[0].n_jobs) == (50, 3, 1)


def test_recognition_hop_is_clamped_online(hosted):
    with hosted(min_hop_s=0.25) as client:
        a = Visitor(client)
        calls = []
        a.sandbox.container.recognition.start = lambda model_id, sensor_id, overrides: calls.append(overrides) or {"running": False}
        for body in ({"hop_s": 0.05}, {}, {"hop_s": 0.5}):
            assert a.post("/api/recognition/start", body).status_code == 200
        assert [call["hop_s"] for call in calls] == [0.25, 0.25, 0.5]


def dependency_calls(dependant):
    for dependency in dependant.dependencies:
        yield dependency.call
        yield from dependency_calls(dependency)


def test_every_stateful_api_route_resolves_a_sandbox(hosted):
    with hosted() as client:
        unguarded = []
        for route in client.app.routes:
            if not isinstance(route, APIRoute) or not route.path.startswith("/api/") or route.path == "/api/session":
                continue
            if route.methods <= {"GET", "HEAD"} and route.path in STATELESS_GETS:
                continue
            if get_container not in set(dependency_calls(route.dependant)):
                unguarded.append(f"{sorted(route.methods)} {route.path}")
        assert unguarded == []


def test_startup_cleanup_only_removes_sandbox_folders(tmp_path):
    root = tmp_path / "sandboxes"
    (root / "sbx-0123456789abcdef").mkdir(parents=True)
    (root / "keep-me").mkdir()
    (root / "notes.txt").write_text("keep", encoding="utf-8")
    with TestClient(make_hosted_app(tmp_path)):
        pass
    assert not (root / "sbx-0123456789abcdef").exists()
    assert (root / "keep-me").is_dir()
    assert (root / "notes.txt").is_file()


def test_hosted_limits_come_from_the_environment_and_are_clamped(monkeypatch):
    monkeypatch.setenv("GESTURE_TO_PC_MAX_SANDBOXES", "7")
    monkeypatch.setenv("GESTURE_TO_PC_MAX_TREES", "99999")
    monkeypatch.setenv("GESTURE_TO_PC_MIN_HOP_S", "not-a-number")
    monkeypatch.setenv("GESTURE_TO_PC_PROJECT_URL", "https://example.org/repo")
    limits = HostedLimits.from_env()
    assert limits.max_sandboxes == 7
    assert limits.max_trees == 2000
    assert limits.min_hop_s == HostedLimits().min_hop_s
    assert limits.project_url == "https://example.org/repo"


def test_only_hosted_mode_listens_beyond_this_pc(tmp_path, monkeypatch):
    monkeypatch.setenv("PORT", "12345")
    config = hosted_config(AppPaths.isolated(tmp_path))
    assert (config.host, config.port, config.enable_os_control, config.enable_global_hotkey) == ("0.0.0.0", 12345, False, False)
    assert AppConfig(paths=AppPaths.isolated(tmp_path), bind_host="0.0.0.0").host == "127.0.0.1"


def test_local_session_reports_that_it_is_not_hosted(api):
    session = api.get("/api/session").json()
    assert session["hosted"] is False
    assert session["limits"] is None
    assert session["bind_host"] == "127.0.0.1"
