from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..processing.csv_io import read_imu_csv
from ..processing.timeline import timeline_seconds
from ..processing.timestamps import classify_timestamps
from .features.registry import FeatureSpec, WindowRejected

SHIFTS_S = (-0.25, -0.12, 0.12, 0.25)
PEAK_SMOOTH_S = 0.05
WHOLE_TRIAL_TOLERANCE_S = 0.06


@dataclass
class MemberSignal:
    t_us: np.ndarray
    values: np.ndarray
    epoch: np.ndarray
    timeline: np.ndarray


@dataclass
class WindowSet:
    X: np.ndarray
    y: np.ndarray
    groups: np.ndarray
    meta: list = field(default_factory=list)
    rejected: Counter = field(default_factory=Counter)
    members_without_windows: list = field(default_factory=list)


def load_member_signal(member: dict) -> MemberSignal:
    if member.get("derivative_file"):
        table = read_imu_csv(Path(member["derivative_file"]))
        mask = table.valid_rows
        epoch = table.epoch.astype(np.int64) if table.epoch is not None else np.zeros(table.n, dtype=np.int64)
        t, v, e = table.t_us[mask], table.values[mask], epoch[mask]
    else:
        table = read_imu_csv(Path(member["file"]), time_unit=member.get("time_unit") if member.get("header_alias") == "time" else None)
        analysis = classify_timestamps(table.t_us, valid=table.valid_rows)
        good = analysis.good_mask & table.valid_rows
        t, v, e = analysis.t_us[good], table.values[good], analysis.epoch[good].astype(np.int64)
    return MemberSignal(t, v, e, timeline_seconds(t, e))


def smoothed_gyro_magnitude(t_us: np.ndarray, values: np.ndarray) -> np.ndarray:
    gyro = np.sqrt(np.sum(values[:, 3:6] ** 2, axis=1))
    if len(t_us) < 3:
        return gyro
    dt = np.median(np.diff(t_us)) / 1e6
    width = max(1, int(round(PEAK_SMOOTH_S / max(dt, 1e-4))))
    return np.convolve(gyro, np.ones(width) / width, mode="same")


def window_plan(member: dict, signal: MemberSignal, window_s: float, augment: bool, idle_ids: set[str], whole_trial_ok: bool) -> tuple[list[tuple[float, float]], str | None]:
    if len(signal.t_us) == 0:
        return [], "no_samples"
    segment = member.get("segment")
    if segment:
        mask = (signal.timeline >= segment["start_s"]) & (signal.timeline <= segment["end_s"])
    else:
        mask = np.ones(len(signal.t_us), dtype=bool)
    idx = np.flatnonzero(mask)
    if len(idx) == 0:
        return [], "segment_has_no_samples"
    epochs, counts = np.unique(signal.epoch[idx], return_counts=True)
    epoch = epochs[int(np.argmax(counts))]
    idx = idx[signal.epoch[idx] == epoch]
    epoch_idx = np.flatnonzero(signal.epoch == epoch)
    t_epoch_first = float(signal.t_us[epoch_idx[0]])
    t_epoch_last = float(signal.t_us[epoch_idx[-1]])
    t_first, t_last = float(signal.t_us[idx[0]]), float(signal.t_us[idx[-1]])
    span_s = (t_last - t_first) / 1e6
    width_us = window_s * 1e6
    if whole_trial_ok and not segment and span_s <= window_s + WHOLE_TRIAL_TOLERANCE_S:
        return [(t_first, span_s + 1e-6)], None
    if (t_epoch_last - t_epoch_first) < width_us - 1e3:
        return [], "shorter_than_window"
    is_idle = member.get("label_id") in idle_ids
    if is_idle and span_s >= 1.5 * window_s:
        starts = list(np.arange(t_first, t_last - width_us + 1, width_us))
    else:
        smooth = smoothed_gyro_magnitude(signal.t_us[epoch_idx], signal.values[epoch_idx])
        local = np.searchsorted(epoch_idx, idx)
        peak_local = local[int(np.argmax(smooth[local]))]
        t_peak = float(signal.t_us[epoch_idx[peak_local]])
        base = t_peak - width_us / 2
        offsets = (0.0, *SHIFTS_S) if augment else (0.0,)
        starts = [base + o * 1e6 for o in offsets]
    plans = []
    seen = set()
    for start in starts:
        clamped = min(max(start, t_epoch_first), t_epoch_last - width_us)
        key = round(clamped / 1e3)
        if key in seen:
            continue
        seen.add(key)
        plans.append((clamped, window_s))
    return plans, None


def build_windows(members: list[dict], spec: FeatureSpec, window_s: float, src_dir: Path, augment: bool, idle_ids: set[str], progress=None) -> WindowSet:
    X, y, groups, meta = [], [], [], []
    rejected: Counter = Counter()
    empty: list[dict] = []
    cache: dict[str, MemberSignal] = {}
    whole_trial_ok = not spec.resamples
    for i, member in enumerate(members):
        key = member.get("derivative_file") or member["file"]
        if key not in cache:
            cache[key] = load_member_signal(member)
        signal = cache[key]
        plans, reason = window_plan(member, signal, window_s, augment and spec.resamples, idle_ids, whole_trial_ok)
        if reason:
            rejected[reason] += 1
            empty.append({"recording_id": member["recording_id"], "segment_id": member.get("segment_id"), "reason": reason})
            continue
        made = 0
        for start_us, length_s in plans:
            try:
                features = spec.window_features(signal.t_us, signal.values, start_us, length_s, src_dir)
            except WindowRejected as exc:
                rejected[exc.reason] += 1
                continue
            if not np.all(np.isfinite(features)):
                rejected["non_finite_features"] += 1
                continue
            X.append(features)
            y.append(member["label_id"])
            groups.append(member["group"])
            meta.append({"recording_id": member["recording_id"], "segment_id": member.get("segment_id"), "start_us": start_us, "window_s": length_s})
            made += 1
        if made == 0:
            empty.append({"recording_id": member["recording_id"], "segment_id": member.get("segment_id"), "reason": "all windows rejected"})
        if progress:
            progress(i + 1, len(members))
    dims = len(spec.feature_names)
    return WindowSet(
        X=np.asarray(X, dtype=np.float64).reshape(-1, dims),
        y=np.asarray(y, dtype=object),
        groups=np.asarray(groups, dtype=object),
        meta=meta,
        rejected=rejected,
        members_without_windows=empty,
    )
