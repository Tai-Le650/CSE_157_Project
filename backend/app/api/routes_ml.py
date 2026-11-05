from __future__ import annotations

from fastapi import APIRouter, Response

from ..control.actions import allowlist_description
from ..ml.features.registry import FEATURES
from ..ml.training import TrainingConfig
from ..schemas.ml import ActiveProfile, ConfirmRequest, MappingUpsert, ModelPatch, ProfileCreate, ProfilePatch, RecognitionStart, SimulateRequest
from .deps import Container
from .errors import conflict

training = APIRouter(prefix="/api/training", tags=["training"])
models = APIRouter(prefix="/api/models", tags=["models"])
recognition = APIRouter(prefix="/api/recognition", tags=["recognition"])
mappings = APIRouter(prefix="/api/mappings", tags=["mappings"])


@training.get("/features", summary="Available versioned feature pipelines")
def features() -> list[dict]:
    return [{"version": f.version, "preprocessing": f.preprocessing, "default_window_s": f.default_window_s, "min_samples": f.min_samples, "feature_count": len(f.feature_names), "feature_names": list(f.feature_names), "description": f.description} for f in FEATURES.values()]


@training.post("/jobs", status_code=201, summary="Start a background training job", description="Runs in a separate process. Evaluation uses grouped cross-validation (StratifiedGroupKFold by session, else recording). Progress streams on the 'training' WebSocket topic.")
def start_job(body: TrainingConfig, c: Container) -> dict:
    return c.training.start(body)


@training.get("/jobs", summary="Recent training jobs")
def list_jobs(c: Container) -> list[dict]:
    return c.training.list_jobs()


@training.get("/jobs/{job_id}", summary="Training job status and results")
def get_job(job_id: str, c: Container) -> dict:
    return c.training.get_job(job_id)


@training.post("/jobs/{job_id}/cancel", summary="Cancel a running job (terminates the worker process)")
def cancel_job(job_id: str, c: Container) -> dict:
    return c.training.cancel(job_id)


@models.get("", summary="Models in the current mode, with compatibility checks")
def list_models(c: Container) -> list[dict]:
    return c.registry.list(c.settings.current.selected_model_id)


@models.get("/{model_id}", summary="Model detail including the full manifest")
def get_model(model_id: str, c: Container) -> dict:
    return c.registry.detail(model_id, c.settings.current.selected_model_id)


@models.post("/{model_id}/select", summary="Select the model used by Live Recognition")
def select_model(model_id: str, c: Container) -> dict:
    detail = c.registry.detail(model_id)
    if not detail["compatibility"]["compatible"]:
        raise conflict("model_incompatible", "This model cannot be selected", detail["compatibility"])
    if c.recognition.running and c.recognition.model and c.recognition.model.model_id != model_id:
        c.recognition.stop("model_changed")
    c.settings.update({"selected_model_id": model_id})
    c.activity.info("training", f"Selected model {detail['name']}", model_id=model_id)
    return c.registry.detail(model_id, model_id)


@models.post("/{model_id}/trust", summary="Trust a local legacy CLI model after confirmation (joblib can execute code)")
def trust_model(model_id: str, body: ConfirmRequest, c: Container) -> dict:
    return c.registry.trust(model_id, body.confirm)


@models.patch("/{model_id}", summary="Rename a model")
def rename_model(model_id: str, body: ModelPatch, c: Container) -> dict:
    return c.registry.rename(model_id, body.name)


@models.delete("/{model_id}", summary="Delete an app-trained model (legacy CLI files are only unregistered)")
def delete_model(model_id: str, c: Container, confirm: bool = False) -> dict:
    if c.recognition.running and c.recognition.model and c.recognition.model.model_id == model_id:
        c.recognition.stop("model_deleted")
    result = c.registry.delete(model_id, confirm)
    if c.settings.current.selected_model_id == model_id:
        c.settings.update({"selected_model_id": None})
    return result


@recognition.get("", summary="Recognition state, last prediction and recent detections")
def state(c: Container) -> dict:
    return c.recognition.state()


@recognition.post("/start", summary="Start continuous recognition")
def start(body: RecognitionStart, c: Container) -> dict:
    overrides = body.model_dump(exclude_none=True, exclude={"model_id", "sensor_id"})
    return c.recognition.start(body.model_id, body.sensor_id, overrides)


@recognition.post("/stop", summary="Stop recognition (also disarms PC control)")
def stop(c: Container) -> dict:
    return c.recognition.stop("user")


@mappings.get("/profiles", summary="Mapping profiles and their mappings")
def profiles(c: Container) -> list[dict]:
    return c.mappings.profiles()


@mappings.post("/profiles", status_code=201, summary="Create a profile (optionally copying another; copied entries start disabled)")
def create_profile(body: ProfileCreate, c: Container) -> dict:
    return c.mappings.create_profile(body.name, body.description, body.copy_from)


@mappings.patch("/profiles/{profile_id}", summary="Rename a profile")
def patch_profile(profile_id: str, body: ProfilePatch, c: Container) -> dict:
    return c.mappings.update_profile(profile_id, body.name, body.description)


@mappings.delete("/profiles/{profile_id}", status_code=204, summary="Delete a profile")
def delete_profile(profile_id: str, c: Container) -> Response:
    c.mappings.delete_profile(profile_id)
    return Response(status_code=204)


@mappings.put("/active", summary="Choose the active profile (disarms PC control if it changes)")
def set_active(body: ActiveProfile, c: Container) -> dict:
    return c.mappings.set_active(body.profile_id)


@mappings.put("/profiles/{profile_id}/labels/{label_id}", summary="Create or update a mapping (allowlisted actions only)")
def upsert(profile_id: str, label_id: str, body: MappingUpsert, c: Container) -> dict:
    return c.mappings.upsert(profile_id, label_id, body.action, body.enabled)


@mappings.delete("/profiles/{profile_id}/labels/{label_id}", summary="Remove a mapping")
def remove(profile_id: str, label_id: str, c: Container) -> dict:
    return c.mappings.remove(profile_id, label_id)


@mappings.post("/simulate", summary="Describe what a mapping would do without touching the OS")
def simulate(body: SimulateRequest, c: Container) -> dict:
    return c.mappings.simulate(body.label_id, body.action)


@mappings.get("/allowlist", summary="Allowed action types and keys")
def allowlist() -> dict:
    return allowlist_description()
