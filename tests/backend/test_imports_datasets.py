from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import BASE_URL, FIXTURES, Api


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def ref_api(app_factory, tmp_path):
    reference = tmp_path / "reference"
    recordings = reference / "imu_capture" / "recordings"
    recordings.mkdir(parents=True)
    shutil.copy(FIXTURES / "glitch.csv", recordings / "swipe_left.csv")
    shutil.copy(FIXTURES / "trial_time_us.csv", recordings / "swipe_right.csv")
    cli = tmp_path / "cli_data"
    cli.mkdir()
    shutil.copy(FIXTURES / "idle_0001.csv", cli / "idle_0001.csv")
    shutil.copy(FIXTURES / "swipe_left_0001.csv", cli / "swipe_left_0001.csv")
    (cli / "notes.csv").write_text("x\n")
    app = app_factory(reference_root=reference)
    with TestClient(app, base_url=BASE_URL) as client:
        api = Api(client)
        api.reference = reference
        api.cli = cli
        yield api


def test_known_source_import_copies_with_provenance(ref_api):
    sources = {s["key"]: s for s in ref_api.get("/api/imports/known").json()}
    assert sources["imu_capture/swipe_left"]["exists"] is True
    assert sources["imu_capture/wrist_rotation"]["exists"] is False
    original = ref_api.reference / "imu_capture" / "recordings" / "swipe_left.csv"
    before = sha(original)
    result = ref_api.post("/api/imports/known", {"keys": ["imu_capture/swipe_left", "imu_capture/wrist_rotation"]}).json()
    assert len(result["imported"]) == 1
    assert result["skipped"][0]["key"] == "imu_capture/wrist_rotation"
    imported = result["imported"][0]
    assert imported["validation_state"] == "flagged"
    assert sha(original) == before
    detail = ref_api.get(f"/api/recordings/{imported['recording_id']}").json()
    assert detail["kind"] == "continuous"
    assert detail["label_id"] == "swipe_left"
    assert detail["provenance"]["source_sha256"] == before
    assert detail["provenance"]["copied_sha256"] == before
    assert detail["start_time"] is None
    assert sha(Path(detail["file"]["absolute"])) == before
    again = ref_api.post("/api/imports/known", {"keys": ["imu_capture/swipe_left"]}).json()
    assert again["imported"] == [] and again["skipped"][0]["reason"] == "already imported"


def test_upload_requires_unit_and_rejects_bad_files(ref_api):
    content = (FIXTURES / "trial_time_seconds.csv").read_bytes()
    missing = ref_api.client.post("/api/imports/upload", headers=ref_api.headers, files={"file": ("t.csv", content, "text/csv")}, data={"kind": "trial", "label_id": "swipe_left"})
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "time_unit_required"
    ok = ref_api.client.post("/api/imports/upload", headers=ref_api.headers, files={"file": ("t.csv", content, "text/csv")}, data={"kind": "trial", "label_id": "swipe_left", "time_unit": "s"})
    assert ok.status_code == 200, ok.text
    bad = ref_api.client.post("/api/imports/upload", headers=ref_api.headers, files={"file": ("m.csv", (FIXTURES / "missing_column.csv").read_bytes(), "text/csv")}, data={"kind": "trial"})
    assert bad.status_code == 422
    assert ref_api.get("/api/recordings").json()["total"] == 1


def test_legacy_rescan_registers_in_place(ref_api):
    result = ref_api.post("/api/imports/legacy/rescan").json()
    assert sorted(result["registered"]) == ["idle_0001.csv", "swipe_left_0001.csv"]
    assert result["skipped"][0]["file"] == "notes.csv"
    items = ref_api.get("/api/recordings?source=legacy_cli").json()["items"]
    assert {i["label_id"] for i in items} == {"idle", "swipe_left"}
    assert all(i["file"]["base"] == "cli_data" for i in items)
    assert all(not i["app_owned"] for i in items)
    target = items[0]
    refused = ref_api.delete(f"/api/recordings/{target['recording_id']}?mode=disk&confirm=true")
    assert refused.status_code == 409
    assert Path(target["file"]["absolute"]).is_file()
    with open(ref_api.cli / "idle_0001.csv", "a", encoding="utf-8") as handle:
        handle.write("5999999,0,0,1,0,0,0\n")
    again = ref_api.post("/api/imports/legacy/rescan").json()
    assert again["changed"] == ["idle_0001.csv"]


def test_imports_blocked_in_demo_mode(ref_api):
    ref_api.enable_demo()
    response = ref_api.post("/api/imports/known", {"keys": ["imu_capture/swipe_left"]})
    assert response.status_code == 409


def test_dataset_membership_readiness_repair_export(ref_api):
    ref_api.post("/api/imports/legacy/rescan")
    imported = ref_api.post("/api/imports/known", {"keys": ["imu_capture/swipe_left"]}).json()["imported"][0]["recording_id"]
    legacy = {i["label_id"]: i["recording_id"] for i in ref_api.get("/api/recordings?source=legacy_cli").json()["items"]}
    ds = ref_api.post("/api/datasets", {"name": "first"}).json()
    added = ref_api.post(f"/api/datasets/{ds['dataset_id']}/members", {"items": [{"recording_id": imported}, {"recording_id": legacy["idle"]}, {"recording_id": legacy["swipe_left"]}]}).json()
    assert added["added"] == 2
    assert "segments" in added["skipped"][0]["reason"]
    ref_api.post(f"/api/recordings/{imported}/segments", {"label_id": "swipe_left", "start_s": 0.5, "end_s": 1.4})
    ref_api.post(f"/api/recordings/{imported}/segments", {"label_id": "idle", "start_s": 2.0, "end_s": 2.9})
    added = ref_api.post(f"/api/datasets/{ds['dataset_id']}/members", {"items": [{"recording_id": imported}]}).json()
    assert added["added"] == 2
    detail = added["dataset"]
    assert detail["member_count"] == 4
    assert detail["by_label"]["swipe_left"]["segments"] == 1
    assert detail["by_label"]["swipe_left"]["trials"] == 1
    problems = {p["code"] for p in detail["readiness"]["problems"]}
    assert "needs_repair" in problems
    assert any(w["code"] == "missing_sessions" for w in detail["readiness"]["warnings"])
    unconfirmed = ref_api.post(f"/api/datasets/{ds['dataset_id']}/repair-flagged", {"recipe_name": "default-v1"})
    assert unconfirmed.status_code == 409
    repaired = ref_api.post(f"/api/datasets/{ds['dataset_id']}/repair-flagged", {"recipe_name": "default-v1", "confirm": True}).json()
    assert repaired["derivatives_created"] == 1
    assert repaired["dataset"]["readiness"]["ready"] is True
    rec = ref_api.get(f"/api/recordings/{imported}").json()
    assert rec["derivatives"][0]["recipe_name"] == "default-v1"
    manifest = Path(ref_api.container.paths.data_dir / rec["derivatives"][0]["file_path"]).with_name(rec["derivatives"][0]["derivative_id"] + ".manifest.json")
    assert manifest.is_file()
    export = ref_api.post(f"/api/datasets/{ds['dataset_id']}/export")
    assert export.status_code == 200
    archive = ref_api.container.paths.exports_dir("real")
    zips = list(archive.glob("*.zip"))
    with zipfile.ZipFile(zips[0]) as z:
        names = z.namelist()
    assert "manifest.json" in names and "labels.csv" in names
    assert any(n.startswith("derived/") for n in names)
    deleted = ref_api.delete(f"/api/datasets/{ds['dataset_id']}").json()
    assert deleted["recordings_untouched"] is True
    assert ref_api.get("/api/recordings").json()["total"] == 3


def test_flagged_spectrum_requires_explicit_recipe(ref_api):
    rid = ref_api.post("/api/imports/known", {"keys": ["imu_capture/swipe_left"]}).json()["imported"][0]["recording_id"]
    refused = ref_api.post("/api/analysis/spectrum", {"source": "recording", "recording_id": rid, "channel": "gz"})
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "repair_required"
    ok = ref_api.post("/api/analysis/spectrum", {"source": "recording", "recording_id": rid, "channel": "gz", "recipe_name": "default-resampled-v1"})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["recipe"] == "default-resampled-v1"
    assert body["fft"]["dominant_hz"] is not None
    assert len(body["stft"]["db"]) == len(body["stft"]["frequency_hz"])


def test_delete_modes_for_app_owned_files(ref_api):
    rid = ref_api.post("/api/imports/known", {"keys": ["imu_capture/swipe_right"]}).json()["imported"][0]["recording_id"]
    detail = ref_api.get(f"/api/recordings/{rid}").json()
    path = Path(detail["file"]["absolute"])
    assert ref_api.delete(f"/api/recordings/{rid}?mode=disk").status_code == 409
    removed = ref_api.delete(f"/api/recordings/{rid}?mode=disk&confirm=true").json()
    assert str(path) in removed["removed_files"]
    assert not path.exists()
    original = ref_api.reference / "imu_capture" / "recordings" / "swipe_right.csv"
    assert original.is_file()


def test_labels_are_never_merged_implicitly(ref_api):
    labels = {l["label_id"]: l for l in ref_api.get("/api/labels").json()}
    assert labels["flick_up"]["enabled"] is False and labels["swipe_up"]["enabled"] is False
    assert labels["wrist_rotation"]["enabled"] is True
    assert ref_api.post("/api/labels/flick_up/rename", {"new_label_id": "swipe_up", "confirm": True}).status_code == 409
    assert ref_api.post("/api/labels/merge", {"source_id": "flick_up", "target_id": "swipe_up"}).status_code == 409
    assert ref_api.patch("/api/labels/idle", {"enabled": False}).status_code == 409
    created = ref_api.post("/api/labels", {"label_id": "thumbs_up", "display_name": "Thumbs Up"})
    assert created.status_code == 201
    assert ref_api.post("/api/labels", {"label_id": "Bad Label", "display_name": "x"}).status_code == 422
