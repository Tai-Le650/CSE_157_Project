from __future__ import annotations

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, Response

from ..processing.repair import PRESETS, resolve_recipe
from ..schemas.recordings import (
    ContinuousStartRequest,
    DerivativeRequest,
    KnownImportRequest,
    LabelCreate,
    LabelMerge,
    LabelPatch,
    LabelRename,
    NewSessionRequest,
    RecordingPatch,
    SegmentCreate,
    SegmentPatch,
    SessionAssign,
    SessionPatch,
    StagingIdsRequest,
    StagingPatch,
    TrialStartRequest,
)
from .deps import Container
from .errors import AppError

recordings = APIRouter(prefix="/api/recordings", tags=["recordings"])
recorder = APIRouter(prefix="/api/recorder", tags=["recorder"])
imports = APIRouter(prefix="/api/imports", tags=["imports"])
labels = APIRouter(prefix="/api/labels", tags=["labels"])
sessions = APIRouter(prefix="/api/sessions", tags=["sessions"])


@recorder.get("", summary="Recorder state and staged (unsaved) trials")
def recorder_state(c: Container) -> dict:
    return c.recorder.snapshot()


@recorder.post("/trials", summary="Start a set of countdown trials", description="Each trial captures every sensor in sensor_ids for duration_s after a countdown. Captured trials go to staging until saved or discarded.")
def start_trials(body: TrialStartRequest, c: Container) -> dict:
    defaults = c.settings.current.recording
    return c.recorder.start_trials(
        body.label_id,
        body.sensor_ids,
        body.duration_s or defaults.trial_duration_s,
        body.countdown_s if body.countdown_s is not None else defaults.countdown_s,
        body.trials or defaults.trials_per_set,
        body.pause_s if body.pause_s is not None else defaults.pause_between_s,
        body.session_id,
        body.notes,
    )


@recorder.post("/continuous", summary="Start a continuous (free-run) recording")
def start_continuous(body: ContinuousStartRequest, c: Container) -> dict:
    return c.recorder.start_continuous(body.label_id, body.sensor_ids, body.session_id, body.notes)


@recorder.post("/stop", summary="Stop the current recording", description="Trials: the unfinished trial is discarded. Continuous: the capture is moved to staging.")
def stop(c: Container) -> dict:
    return c.recorder.stop_recording()


@recorder.post("/session", summary="Start a new recording session (used for grouped evaluation)")
def new_session(body: NewSessionRequest, c: Container) -> dict:
    return c.recorder.new_session(body.name, body.notes)


@recorder.get("/staging/{staging_id}/preview", summary="Preview a staged trial")
def staging_preview(staging_id: str, c: Container, max_points: int = Query(2000, ge=100, le=20000)) -> dict:
    return c.recorder.preview(staging_id, max_points)


@recorder.patch("/staging/{staging_id}", summary="Annotate or relabel a staged trial before saving")
def staging_patch(staging_id: str, body: StagingPatch, c: Container) -> dict:
    return c.recorder.update_staging(staging_id, body.notes, body.label_id)


@recorder.post("/staging/save", summary="Save staged trials into data/raw (immutable)")
def staging_save(body: StagingIdsRequest, c: Container) -> dict:
    return c.recorder.save(body.staging_ids)


@recorder.post("/staging/discard", summary="Permanently delete staged trials (requires confirm=true)")
def staging_discard(body: StagingIdsRequest, c: Container) -> dict:
    return c.recorder.discard(body.staging_ids, body.confirm)


@recorder.get("/staging/{staging_id}/export", summary="Download a staged trial as a legacy 7-column CSV")
def staging_export(staging_id: str, c: Container) -> Response:
    name, text = c.recorder.export_legacy_csv(staging_id)
    return Response(text, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@recordings.get("", summary="Search and filter recordings in the current mode")
def list_recordings(
    c: Container,
    q: str | None = Query(None, max_length=100),
    label_id: str | None = None,
    sensor_id: str | None = None,
    kind: str | None = Query(None, pattern="^(trial|continuous)$"),
    source: str | None = Query(None, pattern="^(live|import|legacy_cli|demo)$"),
    state: str | None = Query(None, pattern="^(valid|flagged|invalid)$"),
    session_id: str | None = None,
    sort: str = Query("created_desc", pattern="^(created_desc|created_asc|duration_desc|label)$"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    return c.library.query(q, label_id, sensor_id, kind, source, state, session_id, sort, limit, offset)


@recordings.post("/recover", summary="Re-register app recordings whose metadata row is missing (from .meta.json files)")
def recover(c: Container) -> dict:
    return c.library.recover_orphans()


@recordings.get("/recipes", summary="Available repair recipe presets")
def recipes() -> list[dict]:
    return [r.model_dump() for r in PRESETS.values()]


@recordings.get("/{recording_id}", summary="Recording metadata, validation report, segments, derivatives and dataset membership")
def get_recording(recording_id: str, c: Container) -> dict:
    return c.library.detail(recording_id)


@recordings.get("/{recording_id}/preview", summary="Decimated signal preview with flagged-row markers and segments")
def preview(recording_id: str, c: Container, max_points: int = Query(2500, ge=100, le=20000), derivative_id: str | None = None) -> dict:
    return c.library.preview(recording_id, max_points, derivative_id)


@recordings.get("/{recording_id}/file", summary="Download the original file exactly as stored")
def download(recording_id: str, c: Container) -> FileResponse:
    detail = c.library.detail(recording_id)
    return FileResponse(detail["file"]["absolute"], media_type="text/csv", filename=f"{recording_id}.csv")


@recordings.patch("/{recording_id}", summary="Relabel, annotate, change kind or session")
def patch_recording(recording_id: str, body: RecordingPatch, c: Container) -> dict:
    changes = body.model_dump(exclude_unset=True, exclude={"clear_label", "clear_session"})
    if body.clear_label:
        changes["label_id"] = None
    if body.clear_session:
        changes["session_id"] = None
    if "session_id" in changes and changes["session_id"]:
        c.sessions.ensure_exists(changes["session_id"])
    return c.library.update(recording_id, changes)


@recordings.delete("/{recording_id}", summary="Remove from the library (mode=metadata) or delete app-owned files (mode=disk)", description="mode=metadata keeps every file on disk. mode=disk is allowed only for files this app created and requires confirm=true.")
def delete_recording(recording_id: str, c: Container, mode: str = Query(..., pattern="^(metadata|disk)$"), confirm: bool = False) -> dict:
    if not confirm:
        raise AppError("confirmation_required", "Deleting needs confirm=true", 409)
    return c.library.delete(recording_id, mode)


@recordings.post("/{recording_id}/revalidate", summary="Recompute validation and check the file hash")
def revalidate(recording_id: str, c: Container) -> dict:
    return c.library.revalidate(recording_id)


@recordings.post("/{recording_id}/segments", status_code=201, summary="Label a time range of a continuous recording")
def add_segment(recording_id: str, body: SegmentCreate, c: Container) -> dict:
    return c.library.add_segment(recording_id, body.label_id, body.start_s, body.end_s, body.notes)


@recordings.patch("/segments/{segment_id}", summary="Edit a segment")
def patch_segment(segment_id: str, body: SegmentPatch, c: Container) -> dict:
    return c.library.update_segment(segment_id, body.model_dump(exclude_unset=True))


@recordings.delete("/segments/{segment_id}", status_code=204, summary="Delete a segment")
def delete_segment(segment_id: str, c: Container) -> Response:
    c.library.delete_segment(segment_id)
    return Response(status_code=204)


@recordings.post("/{recording_id}/derivatives", status_code=201, summary="Create a repaired derivative with an explicit recipe", description="Writes data/processed/<id>.csv plus a manifest with the source hash, recipe and per-step counts. The original stays untouched.")
def create_derivative(recording_id: str, body: DerivativeRequest, c: Container) -> dict:
    recipe = resolve_recipe(body.recipe_name, body.recipe)
    return c.library.create_derivative(recording_id, recipe)


@recordings.delete("/derivatives/{derivative_id}", summary="Delete a derivative (its source recording is untouched)")
def delete_derivative(derivative_id: str, c: Container) -> dict:
    return c.library.delete_derivative(derivative_id)


@imports.get("/known", summary="Reference recordings that can be imported explicitly")
def known(c: Container) -> list[dict]:
    return c.importer.known_sources()


@imports.post("/known", summary="Import selected reference recordings (copied with SHA-256 provenance)")
def import_known(body: KnownImportRequest, c: Container) -> dict:
    return c.importer.import_known(body.keys, body.session_mode, body.session_name)


@imports.post("/upload", summary="Import an uploaded CSV", description="Accepts t_us or time_us (device microseconds), or time with an explicit unit. The file is validated before it is copied.")
async def upload(
    c: Container,
    file: UploadFile = File(...),
    kind: str = Form("trial"),
    label_id: str | None = Form(None),
    time_unit: str | None = Form(None),
    session_id: str | None = Form(None),
    notes: str = Form(""),
) -> dict:
    data = await file.read()
    return c.importer.import_upload(file.filename or "upload.csv", data, kind, label_id or None, time_unit or None, session_id or None, notes)


@imports.post("/legacy/rescan", summary="Register legacy CLI trials found directly under data/*.csv (in place)")
def rescan(c: Container) -> dict:
    return c.importer.rescan_legacy()


@labels.get("", summary="Labels with usage counts")
def list_labels(c: Container) -> list[dict]:
    return c.labels.list()


@labels.post("", status_code=201, summary="Create a custom label")
def create_label(body: LabelCreate, c: Container) -> dict:
    return c.labels.create(body.label_id, body.display_name, body.enabled, body.description)


@labels.patch("/{label_id}", summary="Change a label's display name, description or enabled state")
def patch_label(label_id: str, body: LabelPatch, c: Container) -> dict:
    return c.labels.update(label_id, body.display_name, body.enabled, body.description)


@labels.post("/{label_id}/rename", summary="Rename a custom label ID everywhere (explicit, logged)")
def rename_label(label_id: str, body: LabelRename, c: Container) -> dict:
    return c.labels.rename(label_id, body.new_label_id, body.confirm)


@labels.post("/merge", summary="Merge one label into another (explicit, logged; never automatic)")
def merge_labels(body: LabelMerge, c: Container) -> dict:
    return c.labels.merge(body.source_id, body.target_id, body.confirm)


@labels.delete("/{label_id}", status_code=204, summary="Delete an unused custom label")
def delete_label(label_id: str, c: Container) -> Response:
    c.labels.delete(label_id)
    return Response(status_code=204)


@labels.get("/history/changes", summary="Label change log")
def label_history(c: Container) -> list[dict]:
    return c.labels.history()


@sessions.get("", summary="Recording sessions in the current mode")
def list_sessions(c: Container) -> list[dict]:
    return c.sessions.list()


@sessions.post("", status_code=201, summary="Create a session")
def create_session(body: NewSessionRequest, c: Container) -> dict:
    return c.sessions.create(body.name, body.notes)


@sessions.patch("/{session_id}", summary="Rename or annotate a session")
def patch_session(session_id: str, body: SessionPatch, c: Container) -> dict:
    return c.sessions.update(session_id, body.name, body.notes)


@sessions.post("/assign", summary="Assign recordings to a session (or clear with session_id=null)")
def assign_session(body: SessionAssign, c: Container) -> dict:
    return {"updated": c.sessions.assign(body.session_id, body.recording_ids)}
