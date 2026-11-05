from __future__ import annotations

from pathlib import Path

from conftest import wait_for


def record_trials(api, label="swipe_left", trials=2, duration=1.0, sensor="DEMO-1"):
    response = api.post("/api/recorder/trials", {"label_id": label, "sensor_ids": [sensor], "duration_s": duration, "countdown_s": 0.2, "trials": trials, "pause_s": 0.1})
    assert response.status_code == 200, response.text
    wait_for(lambda: not api.get("/api/recorder").json()["state"]["active"], timeout=15)
    return api.get("/api/recorder").json()


def test_trials_capture_stage_and_save(api):
    api.enable_demo()
    api.connect_demo("1", rate=100)
    wait_for(lambda: api.get("/api/sensors/DEMO-1").json()["status"] == "streaming")
    state = record_trials(api)
    staging = state["staging"]
    assert len(staging) == 2
    for trial in staging:
        assert 85 <= trial["sample_count"] <= 115
        assert trial["validation_state"] == "valid"
        assert trial["source"] == "demo"
        assert trial["label_id"] == "swipe_left"
    assert len({t["recording_id"] for t in staging}) == 2
    preview = api.get(f"/api/recorder/staging/{staging[0]['staging_id']}/preview").json()
    assert max(abs(v) for v in preview["channels"]["gz"]) > 100
    assert api.post("/api/recorder/staging/discard", {"staging_ids": [staging[1]["staging_id"]]}).status_code == 409
    saved = api.post("/api/recorder/staging/save", {"staging_ids": [staging[0]["staging_id"]]}).json()
    assert saved["saved"] == [staging[0]["staging_id"]]
    discarded = api.post("/api/recorder/staging/discard", {"staging_ids": [staging[1]["staging_id"]], "confirm": True}).json()
    assert discarded["discarded"] == [staging[1]["staging_id"]]
    library = api.get("/api/recordings").json()
    assert library["total"] == 1
    item = library["items"][0]
    assert item["workspace"] == "demo"
    assert item["session_id"]
    assert item["file"]["path"].startswith("raw/demo/")
    assert Path(item["file"]["absolute"]).is_file()
    assert Path(item["file"]["absolute"]).with_name(item["recording_id"] + ".meta.json").is_file()
    assert item["fs_median_hz"] and 90 < item["fs_median_hz"] < 110
    detail = api.get(f"/api/recordings/{item['recording_id']}").json()
    assert detail["validation"]["version"] == "validation-v1"
    assert detail["provenance"]["simulated"] is True


def test_stop_discards_unfinished_trial(api):
    api.enable_demo()
    api.connect_demo("1", rate=100)
    wait_for(lambda: api.get("/api/sensors/DEMO-1").json()["status"] == "streaming")
    api.post("/api/recorder/trials", {"label_id": "idle", "sensor_ids": ["DEMO-1"], "duration_s": 3.0, "countdown_s": 0.1, "trials": 3})
    wait_for(lambda: api.get("/api/recorder").json()["state"]["phase"] == "recording")
    api.post("/api/recorder/stop")
    state = api.get("/api/recorder").json()
    assert state["state"]["active"] is False
    assert state["staging"] == []


def test_continuous_recording_and_segments(api):
    api.enable_demo()
    api.connect_demo("1", rate=100)
    wait_for(lambda: api.get("/api/sensors/DEMO-1").json()["status"] == "streaming")
    assert api.post("/api/recorder/continuous", {"sensor_ids": ["DEMO-1"]}).status_code == 200
    api.post("/api/demo/sensors/DEMO-1/perform", {"label": "wrist_rotation"})
    wait_for(lambda: api.get("/api/recorder").json()["state"]["phase"] == "recording")
    import time

    time.sleep(1.5)
    staging = api.post("/api/recorder/stop").json()["staging"]
    assert len(staging) == 1 and staging[0]["kind"] == "continuous"
    api.post("/api/recorder/staging/save", {"staging_ids": [staging[0]["staging_id"]]})
    rid = staging[0]["recording_id"]
    bad = api.post(f"/api/recordings/{rid}/segments", {"label_id": "wrist_rotation", "start_s": 0.5, "end_s": 30})
    assert bad.status_code == 422
    seg = api.post(f"/api/recordings/{rid}/segments", {"label_id": "wrist_rotation", "start_s": 0.0, "end_s": 0.9})
    assert seg.status_code == 201, seg.text
    detail = api.get(f"/api/recordings/{rid}").json()
    assert len(detail["segments"]) == 1


def test_recording_requires_streaming_sensor_and_enabled_label(api):
    api.enable_demo()
    response = api.post("/api/recorder/trials", {"label_id": "swipe_left", "sensor_ids": ["DEMO-9"]})
    assert response.status_code == 404
    api.connect_demo("1")
    wait_for(lambda: api.get("/api/sensors/DEMO-1").json()["status"] == "streaming")
    disabled = api.post("/api/recorder/trials", {"label_id": "circle", "sensor_ids": ["DEMO-1"]})
    assert disabled.status_code == 409
    assert disabled.json()["error"]["code"] == "label_not_enabled"
