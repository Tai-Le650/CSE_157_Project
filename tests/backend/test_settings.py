from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import BASE_URL, Api


def test_defaults_are_safe(api):
    settings = api.get("/api/settings").json()
    assert settings["control"]["pc_control_enabled"] is False
    assert settings["demo_mode"] is False
    assert settings["acquisition"]["default_baud"] == 115200
    assert settings["inference"]["threshold"] == 0.85
    assert settings["inference"]["cooldown_s"] == 1.2


def test_settings_persist_across_restart(app_factory):
    with TestClient(app_factory(), base_url=BASE_URL) as client:
        api = Api(client)
        response = api.patch("/api/settings", {"values": {"theme": "dark", "recording": {"countdown_s": 2}}})
        assert response.status_code == 200, response.text
    with TestClient(app_factory(), base_url=BASE_URL) as client:
        settings = client.get("/api/settings").json()
        assert settings["theme"] == "dark"
        assert settings["recording"]["countdown_s"] == 2
        assert settings["recording"]["trial_duration_s"] == 1.5


def test_invalid_settings_rejected(api):
    response = api.patch("/api/settings", {"values": {"inference": {"threshold": 3}}})
    assert response.status_code == 422
    assert api.get("/api/settings").json()["inference"]["threshold"] == 0.85


def test_demo_mode_needs_dedicated_endpoint_and_confirmation(api):
    assert api.patch("/api/settings", {"values": {"demo_mode": True}}).status_code == 422
    unconfirmed = api.post("/api/settings/demo-mode", {"enabled": True})
    assert unconfirmed.status_code == 409
    assert unconfirmed.json()["error"]["code"] == "confirmation_required"
    assert api.enable_demo()["demo_mode"] is True
    assert api.get("/api/status").json()["primary_mode"] == "Demo"


def test_storage_change_requires_restart(api, tmp_path):
    target = tmp_path / "elsewhere"
    response = api.put("/api/settings/storage", {"data_dir": str(target)})
    assert response.status_code == 200
    body = response.json()
    assert body["restart_required"] is True
    assert body["pending_data_dir"] == str(target.resolve())
