from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.logging_config import RedactTokenFilter, uvicorn_log_config
from conftest import BASE_URL, ORIGIN


def test_health_and_session_are_public(api):
    assert api.get("/api/health").json()["status"] == "ok"
    session = api.get("/api/session").json()
    assert session["token"] == api.token
    assert session["bind_host"] == "127.0.0.1"


def test_state_changing_request_requires_token(api):
    response = api.client.post("/api/control/disarm", json={"reason": "x"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session_token"
    wrong = api.client.post("/api/control/disarm", json={"reason": "x"}, headers={"x-session-token": "nope"})
    assert wrong.status_code == 401
    ok = api.post("/api/control/disarm", {"reason": "x"})
    assert ok.status_code == 200


def test_disallowed_origin_is_rejected_for_rest(api):
    response = api.client.get("/api/status", headers={"origin": "http://evil.example"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_rejected"
    allowed = api.client.get("/api/status", headers={"origin": ORIGIN})
    assert allowed.status_code == 200
    assert allowed.headers.get("access-control-allow-origin") == ORIGIN


def test_cross_site_fetch_metadata_is_rejected(api):
    response = api.client.get("/api/session", headers={"sec-fetch-site": "cross-site"})
    assert response.status_code == 403


def test_untrusted_host_header_is_rejected(app_factory):
    with TestClient(app_factory(), base_url="http://evil.example") as client:
        assert client.get("/api/health").status_code == 400


def test_websocket_requires_token_and_allowed_origin(api):
    with pytest.raises(WebSocketDisconnect) as missing:
        with api.client.websocket_connect("ws://127.0.0.1:8000/ws") as ws:
            ws.receive_json()
    assert missing.value.code == 1008
    with pytest.raises(WebSocketDisconnect) as bad_origin:
        with api.client.websocket_connect(f"ws://127.0.0.1:8000/ws?token={api.token}", headers={"origin": "http://evil.example"}) as ws:
            ws.receive_json()
    assert bad_origin.value.code == 1008


def test_websocket_hello_contains_snapshot(api):
    with api.ws() as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["v"] == 1
        snapshot = hello["data"]["snapshot"]
        assert snapshot["status"]["workspace"] == "real"
        assert snapshot["control"]["armed"] is False
        assert len(hello["data"]["client_id"]) == 12


def test_validation_errors_are_structured(api):
    response = api.post("/api/sensors", {"sensor_id": "", "bogus": 1})
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert any("sensor_id" in item["loc"] for item in body["details"])


def test_unknown_api_route_is_json_404(api):
    response = api.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_session_token_is_redacted_from_server_logs():
    record = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, '%s - "WebSocket %s" [accepted]', ("127.0.0.1:5000", "/ws?token=secret-value&x=1"), None)
    assert RedactTokenFilter().filter(record) is True
    message = record.getMessage()
    assert "secret-value" not in message
    assert "/ws?token=[redacted]&x=1" in message
    handlers = uvicorn_log_config()["handlers"]
    assert handlers and all("redact_token" in handler["filters"] for handler in handlers.values())
