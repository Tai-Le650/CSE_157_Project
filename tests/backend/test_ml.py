from __future__ import annotations

import importlib.util
import json
import shutil
import time

import joblib
import numpy as np
import pytest
from sklearn.ensemble import RandomForestClassifier

from app.ml.evaluation import grouped_evaluation
from app.ml.features import stats_spectral_v1, summary60_v1
from app.ml.features.registry import FEATURES, WindowRejected
from conftest import FIXTURES, ROOT, wait_for


def legacy_imu_utils():
    spec = importlib.util.spec_from_file_location("imu_utils_direct", ROOT / "src" / "imu_utils.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_summary60_matches_golden_vector_and_cli():
    golden = json.loads((FIXTURES / "summary60_golden.json").read_text())
    rows = np.genfromtxt(FIXTURES / golden["input"], delimiter=",", skip_header=1)
    delegated = summary60_v1.extract(rows, ROOT / "src")
    assert delegated.shape == (60,)
    assert np.allclose(delegated, golden["features"], atol=1e-12)
    direct = legacy_imu_utils().extract_features(rows)
    assert np.array_equal(delegated, direct)
    assert len(summary60_v1.FEATURE_NAMES) == 60
    assert summary60_v1.legacy_constants(ROOT / "src") == {"window_seconds": 0.9, "min_samples": 30, "baud": 115200}


def test_summary60_window_requires_min_samples():
    spec = FEATURES["summary-60-v1"]
    t = np.arange(20) * 10_000.0
    with pytest.raises(WindowRejected) as err:
        spec.window_features(t, np.zeros((20, 6)), 0.0, 0.9, ROOT / "src")
    assert err.value.reason == "insufficient_samples"


def test_stats_spectral_features():
    fs = 104.0
    t_us = np.arange(0, 1.2, 1 / fs) * 1e6
    values = np.zeros((len(t_us), 6))
    values[:, 2] = 1.0
    values[:, 5] = 100 * np.sin(2 * np.pi * 5 * t_us / 1e6)
    spec = FEATURES["stats-spectral-v1"]
    features = spec.window_features(t_us, values, 0.0, 1.0, ROOT / "src")
    names = list(stats_spectral_v1.FEATURE_NAMES)
    assert features.shape == (64,)
    assert np.all(np.isfinite(features))
    assert abs(features[names.index("gz_dominant_hz")] - 5.0) <= 1.0
    assert abs(features[names.index("az_mean")] - 1.0) < 1e-9
    gapped = np.delete(np.arange(len(t_us)), range(40, 50))
    with pytest.raises(WindowRejected) as err:
        spec.window_features(t_us[gapped], values[gapped], 0.0, 1.0, ROOT / "src")
    assert err.value.reason == "gap_too_large"


def synthetic(n_groups=4, per=6, seed=0):
    rng = np.random.default_rng(seed)
    X, y, groups = [], [], []
    for g in range(n_groups):
        for label, center in (("idle", 0.0), ("swipe_left", 3.0)):
            for _ in range(per):
                X.append(rng.normal(center, 1.0, 5))
                y.append(label)
                groups.append(f"session:{g}")
    return np.array(X), np.array(y, dtype=object), np.array(groups, dtype=object)


def test_grouped_evaluation_never_leaks_groups():
    X, y, groups = synthetic()
    result = grouped_evaluation(X, y, groups, lambda: RandomForestClassifier(n_estimators=20, random_state=0))
    assert result["status"] == "evaluated"
    assert result["n_splits"] == 4
    for fold in result["folds"]:
        assert len(fold["test_groups"]) >= 1
    tested = [g for fold in result["folds"] for g in fold["test_groups"]]
    assert len(tested) == len(set(tested)) == 4
    assert result["confusion_matrix"]["labels"] == ["idle", "swipe_left"]
    assert sum(map(sum, result["confusion_matrix"]["matrix"])) == len(y)


def test_insufficient_grouped_data_reports_instead_of_metrics():
    X, y, groups = synthetic(n_groups=1)
    result = grouped_evaluation(X, y, groups, lambda: RandomForestClassifier(n_estimators=10))
    assert result["status"] == "insufficient_grouped_data"
    assert "accuracy" not in result
    assert sorted(result["classes_lacking_groups"]) == ["idle", "swipe_left"]


def make_legacy_artifact(models_dir, src):
    module = legacy_imu_utils()
    rows = np.genfromtxt(FIXTURES / "swipe_left_0001.csv", delimiter=",", skip_header=1)
    idle_rows = np.genfromtxt(FIXTURES / "idle_0001.csv", delimiter=",", skip_header=1)
    X = np.vstack([module.extract_features(rows + np.random.default_rng(i).normal(0, 0.01, rows.shape)) for i in range(5)] + [module.extract_features(idle_rows + np.random.default_rng(i).normal(0, 0.01, idle_rows.shape)) for i in range(5)])
    y = ["swipe_left"] * 5 + ["idle"] * 5
    model = RandomForestClassifier(n_estimators=20, random_state=42).fit(X, y)
    models_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "feature_version": "summary-60-v1", "window_seconds": 0.9}, models_dir / "gestures.joblib")


def test_legacy_model_requires_trust_and_hash(api):
    paths = api.container.paths
    make_legacy_artifact(paths.models_dir, paths.src_dir)
    models = api.get("/api/models").json()
    legacy = next(m for m in models if m["source"] == "legacy_cli")
    assert legacy["trusted"] is False
    assert legacy["compatibility"]["compatible"] is False
    assert api.post(f"/api/models/{legacy['model_id']}/select").status_code == 409
    assert api.post(f"/api/models/{legacy['model_id']}/trust", {"confirm": False}).status_code == 409
    trusted = api.post(f"/api/models/{legacy['model_id']}/trust", {"confirm": True}).json()
    assert trusted["trusted"] is True
    assert trusted["labels"] == ["idle", "swipe_left"]
    assert trusted["compatibility"]["compatible"] is True
    assert any("not recorded" in w for w in trusted["compatibility"]["warnings"])
    loaded = api.container.registry.load(legacy["model_id"])
    assert loaded.feature.version == "summary-60-v1"
    with open(paths.models_dir / "gestures.joblib", "ab") as handle:
        handle.write(b"tamper")
    rescanned = next(m for m in api.get("/api/models").json() if m["source"] == "legacy_cli")
    assert rescanned["trusted"] is False
    deleted = api.delete(f"/api/models/{legacy['model_id']}?confirm=true").json()
    assert (paths.models_dir / "gestures.joblib").is_file()
    assert deleted["removed"] == []


def record(api, label, trials, sensor="DEMO-1"):
    response = api.post("/api/recorder/trials", {"label_id": label, "sensor_ids": [sensor], "duration_s": 1.25, "countdown_s": 0.05, "trials": trials, "pause_s": 0.05})
    assert response.status_code == 200, response.text
    wait_for(lambda: not api.get("/api/recorder").json()["state"]["active"], timeout=30)


@pytest.mark.slow
def test_end_to_end_demo_record_train_recognize_control(api):
    api.enable_demo()
    api.connect_demo("1", rate=100)
    wait_for(lambda: api.get("/api/sensors/DEMO-1").json()["status"] == "streaming")
    labels = ["idle", "swipe_left", "swipe_right", "wrist_rotation"]
    for session in range(2):
        api.post("/api/recorder/session", {"name": f"demo session {session}"})
        for label in labels:
            record(api, label, 2)
    staging = api.get("/api/recorder").json()["staging"]
    assert len(staging) == 16
    api.post("/api/recorder/staging/save", {"staging_ids": [s["staging_id"] for s in staging]})
    recordings = api.get("/api/recordings").json()["items"]
    assert len(recordings) == 16 and len({r["session_id"] for r in recordings}) == 2
    ds = api.post("/api/datasets", {"name": "demo set"}).json()
    detail = api.post(f"/api/datasets/{ds['dataset_id']}/members", {"items": [{"recording_id": r["recording_id"]} for r in recordings]}).json()["dataset"]
    assert detail["readiness"]["ready"] is True, detail["readiness"]
    job = api.post("/api/training/jobs", {"dataset_id": ds["dataset_id"], "n_estimators": 60}).json()
    rates = []
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        state = api.get(f"/api/training/jobs/{job['job_id']}").json()
        sensor = api.get("/api/sensors/DEMO-1").json()
        rates.append((sensor["status"], sensor["rates"]["device_hz"]))
        if state["status"] in ("done", "failed"):
            break
        time.sleep(0.25)
    assert state["status"] == "done", state
    assert all(status == "streaming" for status, _ in rates)
    measured = [r for _, r in rates if r]
    assert measured and min(measured) > 95.0
    evaluation = state["result"]["evaluation"]
    assert evaluation["status"] == "evaluated"
    assert evaluation["n_splits"] == 2
    assert set(evaluation["groups_per_label"].values()) == {2}
    model_id = state["model_id"]
    model = api.get(f"/api/models/{model_id}").json()
    assert model["workspace"] == "demo" and model["trusted"] is True
    assert model["manifest"]["training_data"]["group_kind"] == "session"
    assert model["manifest"]["rate_requirements"]["training_fs_min_hz"] > 90
    assert api.post(f"/api/models/{model_id}/select").status_code == 200
    started = api.post("/api/recognition/start", {"sensor_id": "DEMO-1", "threshold": 0.5, "debounce_n": 1, "smoothing_k": 2})
    assert started.status_code == 200, started.text
    profile = api.post("/api/mappings/profiles", {"name": "demo actions"}).json()
    api.put("/api/mappings/active", {"profile_id": profile["profile_id"]})
    api.put(f"/api/mappings/profiles/{profile['profile_id']}/labels/swipe_left", {"action": {"type": "hotkey", "modifiers": ["ctrl", "shift"], "key": "tab"}, "enabled": True})
    api.put(f"/api/mappings/profiles/{profile['profile_id']}/labels/wrist_rotation", {"action": {"type": "scroll", "notches": -3}, "enabled": True})
    api.patch("/api/settings", {"values": {"control": {"pc_control_enabled": True}}})
    with api.ws() as ws:
        client_id = ws.receive_json()["data"]["client_id"]
        ws.send_json({"type": "heartbeat"})
        armed = api.post("/api/control/arm", {"control_session_id": client_id, "confirm": True})
        assert armed.status_code == 200, armed.text
        assert armed.json()["simulated_actions"] is True
        detections = []
        for attempt in range(6):
            api.post("/api/demo/sensors/DEMO-1/perform", {"label": "swipe_left"})
            for _ in range(15):
                ws.send_json({"type": "heartbeat"})
                time.sleep(0.2)
            detections = api.get("/api/recognition").json()["detections"]
            if any(d["label"] == "swipe_left" for d in detections):
                break
        assert any(d["label"] == "swipe_left" for d in detections), detections
        history = api.get("/api/control").json()["history"]
        simulated = [h for h in history if h["outcome"] == "simulated"]
        assert simulated, history
        assert simulated[0]["workspace"] == "demo"
        stop = api.post("/api/control/emergency-stop", {"source": "test"}).json()
        assert stop["estop_latched"] is True and stop["armed"] is False
        assert api.post("/api/control/arm", {"control_session_id": client_id, "confirm": True}).status_code == 409
        api.post("/api/control/reset")
    assert all(not d.get("label") == "idle" for d in api.get("/api/recognition").json()["detections"])
    api.post("/api/recognition/stop")
