from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from ..api.errors import AppError
from .csv_io import ImuTable
from .timestamps import EXCLUDED_FLAGS, classify_timestamps

RECIPE_VERSION = "repair-v1"


class RepairStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal[
        "drop_invalid_rows",
        "drop_duplicate_timestamps",
        "drop_timestamp_glitches",
        "unwrap_micros",
        "segments",
        "gaps",
        "resample",
    ]
    mode: Literal["split_at_resets", "longest", "longest_monotonic_raw"] | None = None
    max_factor: float | None = Field(None, gt=1, le=10)
    max_interpolate_ms: float | None = Field(None, gt=0, le=1000)
    target_hz: float | None = Field(None, gt=1, le=2000)
    use_measured_median: bool | None = None


class RepairRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field("custom", max_length=48)
    version: Literal["repair-v1"] = RECIPE_VERSION
    description: str = ""
    steps: list[RepairStep] = Field(min_length=1, max_length=12)


PRESETS: dict[str, RepairRecipe] = {
    "default-v1": RepairRecipe(
        name="default-v1",
        description="Drop invalid rows, duplicate timestamps and isolated timestamp glitches; unwrap micros(); split at clock resets and at gaps over 50 ms. Keeps original timestamps (no resampling).",
        steps=[
            RepairStep(op="drop_invalid_rows"),
            RepairStep(op="drop_duplicate_timestamps"),
            RepairStep(op="drop_timestamp_glitches", max_factor=3.0),
            RepairStep(op="unwrap_micros"),
            RepairStep(op="segments", mode="split_at_resets"),
            RepairStep(op="gaps", max_interpolate_ms=50.0),
        ],
    ),
    "default-resampled-v1": RepairRecipe(
        name="default-resampled-v1",
        description="default-v1 followed by linear resampling of each segment to the measured median rate.",
        steps=[
            RepairStep(op="drop_invalid_rows"),
            RepairStep(op="drop_duplicate_timestamps"),
            RepairStep(op="drop_timestamp_glitches", max_factor=3.0),
            RepairStep(op="unwrap_micros"),
            RepairStep(op="segments", mode="split_at_resets"),
            RepairStep(op="gaps", max_interpolate_ms=50.0),
            RepairStep(op="resample", use_measured_median=True),
        ],
    ),
    "legacy-analyze-v1": RepairRecipe(
        name="legacy-analyze-v1",
        description="Reproduces imu_capture/analyze_gesture.py: drop invalid rows, drop consecutive duplicate timestamps, keep the longest run without a backward step (no glitch detection), resample to the median rate.",
        steps=[
            RepairStep(op="drop_invalid_rows"),
            RepairStep(op="drop_duplicate_timestamps"),
            RepairStep(op="segments", mode="longest_monotonic_raw"),
            RepairStep(op="resample", use_measured_median=True),
        ],
    ),
}


@dataclass
class RepairResult:
    t_us: np.ndarray
    values: np.ndarray
    segment: np.ndarray
    epoch: np.ndarray
    uniform: bool
    fs_hz: float | None
    median_interval_us: float
    step_counts: list[dict] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.t_us)

    def segments(self) -> list[tuple[int, int]]:
        if self.n == 0:
            return []
        out = []
        start = 0
        for i in range(1, self.n):
            if self.segment[i] != self.segment[i - 1]:
                out.append((start, i))
                start = i
        out.append((start, self.n))
        return out


def resolve_recipe(name: str | None, recipe: RepairRecipe | None) -> RepairRecipe:
    if recipe is not None:
        return recipe
    if name and name in PRESETS:
        return PRESETS[name]
    raise AppError("unknown_recipe", f"Unknown repair recipe '{name}'", 422, {"presets": list(PRESETS)})


def _median_interval(t: np.ndarray, segment: np.ndarray) -> float:
    if len(t) < 2:
        return 10_000.0
    d = np.diff(t)
    same = segment[1:] == segment[:-1]
    d = d[same & (d > 0)]
    return float(np.median(d)) if len(d) else 10_000.0


def _resample(t: np.ndarray, v: np.ndarray, segment: np.ndarray, epoch: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    out_t, out_v, out_s, out_e = [], [], [], []
    for seg_id in np.unique(segment):
        mask = segment == seg_id
        ts, vs = t[mask], v[mask]
        if len(ts) < 2:
            continue
        rel = (ts - ts[0]) * 1e-6
        grid = np.arange(0.0, rel[-1], 1.0 / fs)
        if len(grid) == 0:
            continue
        cols = [np.interp(grid, rel, vs[:, i]) for i in range(6)]
        out_t.append(ts[0] + grid * 1e6)
        out_v.append(np.column_stack(cols))
        out_s.append(np.full(len(grid), seg_id))
        out_e.append(np.full(len(grid), epoch[mask][0]))
    if not out_t:
        return np.empty(0), np.empty((0, 6)), np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)
    return np.concatenate(out_t), np.vstack(out_v), np.concatenate(out_s).astype(np.int64), np.concatenate(out_e).astype(np.int64)


def apply_recipe(table: ImuTable, recipe: RepairRecipe) -> RepairResult:
    t = table.t_us.copy()
    v = table.values.copy()
    valid = table.valid_rows.copy()
    segment = np.zeros(len(t), dtype=np.int64)
    epoch = np.zeros(len(t), dtype=np.int64)
    counts: list[dict] = []
    uniform = False
    fs: float | None = None
    analysis = None
    unwrapped = False

    def record(op: str, before: int, **details) -> None:
        counts.append({"op": op, "rows_before": before, "rows_after": int(len(t)), "removed": int(before - len(t)), **details})

    for step in recipe.steps:
        before = len(t)
        if step.op == "drop_invalid_rows":
            keep = valid & np.isfinite(t) & np.all(np.isfinite(v), axis=1)
            t, v, segment, valid, epoch = t[keep], v[keep], segment[keep], valid[keep], epoch[keep]
            record(step.op, before)
        elif step.op == "drop_duplicate_timestamps":
            if len(t):
                keep = np.r_[True, np.diff(t) != 0]
                t, v, segment, valid, epoch = t[keep], v[keep], segment[keep], valid[keep], epoch[keep]
            record(step.op, before)
        elif step.op == "drop_timestamp_glitches":
            analysis = classify_timestamps(t, max_factor=step.max_factor or 3.0)
            keep = (analysis.flags & EXCLUDED_FLAGS) == 0
            glitches = int(analysis.stats.glitches)
            t, v, segment, valid, epoch = t[keep], v[keep], segment[keep], valid[keep], epoch[keep]
            analysis = classify_timestamps(t, max_factor=step.max_factor or 3.0)
            record(step.op, before, glitches=glitches)
        elif step.op == "unwrap_micros":
            analysis = classify_timestamps(t)
            wraps = int(analysis.stats.wraps)
            good = (analysis.flags & EXCLUDED_FLAGS) == 0
            t = np.where(good, analysis.t_us, t)
            unwrapped = True
            record(step.op, before, wraps=wraps)
        elif step.op == "segments":
            mode = step.mode or "split_at_resets"
            if mode == "longest_monotonic_raw":
                breaks = np.flatnonzero(np.diff(t) < 0) + 1 if len(t) else np.array([], dtype=np.int64)
                pieces = np.split(np.arange(len(t)), breaks) if len(t) else []
                longest = max(pieces, key=len) if pieces else np.array([], dtype=np.int64)
                t, v, valid = t[longest], v[longest], valid[longest]
                segment = np.zeros(len(t), dtype=np.int64)
                epoch = np.zeros(len(t), dtype=np.int64)
                record(step.op, before, mode=mode, backward_steps=int(len(breaks)), pieces=len(pieces))
            else:
                analysis = classify_timestamps(t)
                epochs = analysis.epoch.copy()
                if not unwrapped:
                    good = (analysis.flags & EXCLUDED_FLAGS) == 0
                    t = np.where(good, analysis.t_us, t)
                if mode == "longest" and len(epochs):
                    values, counts_per = np.unique(epochs, return_counts=True)
                    best = values[int(np.argmax(counts_per))]
                    keep = epochs == best
                    t, v, valid = t[keep], v[keep], valid[keep]
                    segment = np.zeros(len(t), dtype=np.int64)
                    epoch = np.zeros(len(t), dtype=np.int64)
                else:
                    segment = epochs.astype(np.int64)
                    epoch = epochs.astype(np.int64)
                record(step.op, before, mode=mode, clock_segments=int(analysis.stats.epochs))
        elif step.op == "gaps":
            limit_us = (step.max_interpolate_ms or 50.0) * 1000.0
            if len(t):
                new_segment = np.zeros(len(t), dtype=np.int64)
                current = 0
                splits = 0
                for i in range(1, len(t)):
                    if segment[i] != segment[i - 1] or t[i] - t[i - 1] > limit_us:
                        current += 1
                        if segment[i] == segment[i - 1]:
                            splits += 1
                    new_segment[i] = current
                segment = new_segment
            else:
                splits = 0
            record(step.op, before, max_interpolate_ms=step.max_interpolate_ms or 50.0, splits=splits, segments=int(len(np.unique(segment))) if len(t) else 0)
        elif step.op == "resample":
            median = _median_interval(t, segment)
            fs = step.target_hz if step.target_hz else 1e6 / median
            t, v, segment, epoch = _resample(t, v, segment, epoch, fs)
            valid = np.ones(len(t), dtype=bool)
            uniform = True
            record(step.op, before, fs_hz=fs, method="linear")
    median = _median_interval(t, segment)
    if not uniform:
        fs = 1e6 / median if len(t) > 1 else None
    return RepairResult(t_us=t, values=v, segment=segment, epoch=epoch, uniform=uniform, fs_hz=fs, median_interval_us=median, step_counts=counts)
