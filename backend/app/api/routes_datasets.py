from __future__ import annotations

import numpy as np
from fastapi import APIRouter
from fastapi.responses import FileResponse

from ..processing.csv_io import channel_unit, channel_values
from ..processing.repair import apply_recipe, resolve_recipe
from ..processing.spectral import analyze_uniform, uniform_from_samples
from ..schemas.datasets import DatasetCreate, DatasetPatch, MemberDerivative, MembersAdd, MembersRemove, RepairFlagged, SpectrumRequest
from .deps import Container
from .errors import AppError, conflict

datasets = APIRouter(prefix="/api/datasets", tags=["datasets"])
analysis = APIRouter(prefix="/api/analysis", tags=["analysis"])


@datasets.get("", summary="Datasets with class distribution")
def list_datasets(c: Container) -> list[dict]:
    return c.datasets.list()


@datasets.post("", status_code=201, summary="Create a dataset (metadata only; references recordings)")
def create_dataset(body: DatasetCreate, c: Container) -> dict:
    return c.datasets.create(body.name, body.description)


@datasets.get("/{dataset_id}", summary="Dataset members, class distribution and training readiness")
def get_dataset(dataset_id: str, c: Container) -> dict:
    return c.datasets.detail(dataset_id)


@datasets.patch("/{dataset_id}", summary="Rename or describe a dataset")
def patch_dataset(dataset_id: str, body: DatasetPatch, c: Container) -> dict:
    return c.datasets.update(dataset_id, body.name, body.description)


@datasets.delete("/{dataset_id}", summary="Delete a dataset definition (recordings are untouched)")
def delete_dataset(dataset_id: str, c: Container) -> dict:
    return c.datasets.delete(dataset_id)


@datasets.post("/{dataset_id}/members", summary="Add trials or labeled segments", description="Adding a continuous recording without segment_id adds all of its labeled segments.")
def add_members(dataset_id: str, body: MembersAdd, c: Container) -> dict:
    return c.datasets.add_members(dataset_id, [i.model_dump() for i in body.items])


@datasets.post("/{dataset_id}/members/remove", summary="Remove members (recordings stay in the library)")
def remove_members(dataset_id: str, body: MembersRemove, c: Container) -> dict:
    return c.datasets.remove_members(dataset_id, body.member_ids)


@datasets.put("/{dataset_id}/members/{member_id}/derivative", summary="Choose which repaired derivative a member uses")
def member_derivative(dataset_id: str, member_id: int, body: MemberDerivative, c: Container) -> dict:
    return c.datasets.set_member_derivative(dataset_id, member_id, body.derivative_id)


@datasets.post("/{dataset_id}/repair-flagged", summary="Explicitly apply a repair recipe to every flagged member")
def repair_flagged(dataset_id: str, body: RepairFlagged, c: Container) -> dict:
    return c.datasets.repair_flagged(dataset_id, body.recipe_name, body.confirm)


@datasets.post("/{dataset_id}/export", summary="Export the dataset as a ZIP (raw files, derivatives, manifest)")
def export_dataset(dataset_id: str, c: Container) -> FileResponse:
    path = c.datasets.export(dataset_id)
    return FileResponse(path, media_type="application/zip", filename=path.name)


def _longest_segment(t_us: np.ndarray, values: np.ndarray, segment: np.ndarray | None, epoch: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    keys = segment if segment is not None else epoch
    if len(keys) == 0:
        return t_us, values, 0
    uniq, counts = np.unique(keys, return_counts=True)
    best = uniq[int(np.argmax(counts))]
    mask = keys == best
    return t_us[mask], values[mask], int(len(uniq))


@analysis.post("/spectrum", summary="FFT and STFT of a recording, derivative or the live buffer", description="Non-uniform data is linearly resampled to the measured median rate first (reported in the response). Flagged recordings need an explicit recipe or derivative.")
def spectrum(body: SpectrumRequest, c: Container) -> dict:
    info: dict = {"source": body.source, "channel": body.channel, "unit": channel_unit(body.channel)}
    if body.source == "live":
        if not body.sensor_id:
            raise AppError("sensor_required", "sensor_id is required for live spectra", 422)
        session = c.sensors.get(body.sensor_id)
        t, _h, v = session.buffer.window(body.live_seconds)
        if len(t) < body.window:
            raise conflict("insufficient_samples", f"Only {len(t)} live samples buffered; need {body.window}", {"available": int(len(t))})
        segments = 1
        info.update({"sensor_id": body.sensor_id, "simulated": session.simulated, "live_seconds": body.live_seconds})
        uniform = False
        fs = None
    elif body.source == "derivative":
        if not (body.recording_id and body.derivative_id):
            raise AppError("ids_required", "recording_id and derivative_id are required", 422)
        _row, signal = c.library.signal_for(body.recording_id, body.derivative_id)
        t, v, segments = _longest_segment(signal.t_us, signal.values, signal.segment, signal.epoch)
        uniform, fs = signal.uniform, signal.fs_hz
        info.update({"recording_id": body.recording_id, "derivative_id": body.derivative_id})
    else:
        if not body.recording_id:
            raise AppError("recording_required", "recording_id is required", 422)
        if body.recipe_name or body.recipe:
            with c.db() as db:
                row = c.library.get_row(db, body.recording_id)
            recipe = resolve_recipe(body.recipe_name, body.recipe)
            result = apply_recipe(c.library.read_table(row), recipe)
            t, v, segments = _longest_segment(result.t_us, result.values, result.segment, result.epoch)
            uniform, fs = result.uniform, result.fs_hz
            info.update({"recording_id": body.recording_id, "recipe": recipe.name, "step_counts": result.step_counts})
        else:
            row, signal = c.library.signal_for(body.recording_id)
            t, v, segments = _longest_segment(signal.t_us, signal.values, None, signal.epoch)
            uniform, fs = False, None
            info.update({"recording_id": body.recording_id})
    x = channel_values(v, body.channel)
    if uniform and fs:
        series, rate = x, fs
        resampled = False
    else:
        _grid, series, rate = uniform_from_samples(t, x)
        resampled = True
    result = analyze_uniform(series, rate, body.window, body.hop, body.fft_position)
    info.update({"resampled": resampled, "segments_available": segments, "samples_used": int(len(series)), "note": "Linear resampling to the measured median rate; treat spectra of gappy data as exploratory." if resampled else "Uniform derivative used directly."})
    return {**info, **result}
