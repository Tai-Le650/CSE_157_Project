from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

WRAP_US = 1 << 32
WRAP_GUARD_US = 10_000_000
DEFAULT_INTERVAL_US = 10_000.0
GAP_FACTOR = 1.5
BIG_JUMP_FACTOR = 50.0

FLAG_GLITCH = 1
FLAG_DUPLICATE = 2
FLAG_GAP_BEFORE = 4
FLAG_EPOCH_START = 8
FLAG_WRAP = 16
FLAG_INVALID = 32
FLAG_BACKWARD = 64
EXCLUDED_FLAGS = FLAG_GLITCH | FLAG_DUPLICATE | FLAG_INVALID | FLAG_BACKWARD
RESET_MIN_BACKWARD_US = 1_000_000
RESET_BOOT_WINDOW_US = 5_000_000


@dataclass(slots=True)
class Decision:
    payload: Any
    t_raw: int
    t_us: float | None
    epoch: int
    flags: int

    @property
    def good(self) -> bool:
        return not (self.flags & EXCLUDED_FLAGS)


@dataclass
class TimestampStats:
    decided: int = 0
    good: int = 0
    duplicates: int = 0
    glitches: int = 0
    backward_steps: int = 0
    wraps: int = 0
    resets: int = 0
    gaps: int = 0
    estimated_missing: int = 0
    gap_total_us: float = 0.0
    epochs: int = 0

    def as_dict(self) -> dict:
        return {
            "decided": self.decided,
            "good": self.good,
            "duplicates": self.duplicates,
            "glitches": self.glitches,
            "backward_steps": self.backward_steps,
            "wraps": self.wraps,
            "resets": self.resets,
            "gaps": self.gaps,
            "estimated_missing": self.estimated_missing,
            "gap_total_s": self.gap_total_us / 1e6,
            "epochs": self.epochs,
        }


class TimestampClassifier:
    def __init__(self, fixed_median_us: float | None = None, max_factor: float = 3.0, window: int = 64):
        self.fixed_median_us = fixed_median_us
        self.max_factor = max_factor
        self.intervals: deque[float] = deque(maxlen=window)
        self._median_cache = DEFAULT_INTERVAL_US
        self._since_median = 0
        self.prev_t: float | None = None
        self.prev_raw: int | None = None
        self.offset = 0
        self.epoch = -1
        self.pending: tuple[Any, int] | None = None
        self.invalid_since_prev = 0
        self.stats = TimestampStats()

    def median_us(self) -> float:
        if self.fixed_median_us:
            return self.fixed_median_us
        if len(self.intervals) < 8:
            return DEFAULT_INTERVAL_US if not self.intervals else float(np.median(self.intervals))
        if self._since_median >= 16 or self._median_cache == DEFAULT_INTERVAL_US:
            self._median_cache = float(np.median(self.intervals))
            self._since_median = 0
        return self._median_cache

    def push(self, payload: Any, t_raw: int) -> list[Decision]:
        out: list[Decision] = []
        if self.pending is not None:
            out.append(self._decide(self.pending, (payload, t_raw)))
        self.pending = (payload, t_raw)
        return out

    def flush(self) -> list[Decision]:
        if self.pending is None:
            return []
        decision = self._decide(self.pending, None)
        self.pending = None
        return [decision]

    def start_new_epoch(self) -> list[Decision]:
        out = self.flush()
        self.prev_t = None
        self.prev_raw = None
        self.offset = 0
        return out

    def _accept(self, t: float, raw: int, flags: int, payload: Any) -> Decision:
        if self.prev_t is not None:
            delta = t - self.prev_t
            if 0 < delta <= GAP_FACTOR * 2 * self.median_us():
                self.intervals.append(delta)
                self._since_median += 1
        self.prev_t = t
        self.prev_raw = raw
        self.invalid_since_prev = 0
        self.stats.decided += 1
        self.stats.good += 1
        return Decision(payload, raw, t, self.epoch, flags)

    def _gap(self, delta: float, med: float) -> int:
        if delta <= GAP_FACTOR * med:
            return 0
        missing = max(0, int(round(delta / med)) - 1 - self.invalid_since_prev)
        if missing <= 0:
            return 0
        self.stats.gaps += 1
        self.stats.estimated_missing += missing
        self.stats.gap_total_us += delta
        return FLAG_GAP_BEFORE

    def _reject(self, payload: Any, raw: int, t: float | None, flags: int) -> Decision:
        self.stats.decided += 1
        return Decision(payload, raw, t, self.epoch, flags)

    def _decide(self, candidate: tuple[Any, int], following: tuple[Any, int] | None) -> Decision:
        payload, raw = candidate
        med = self.median_us()
        if self.prev_t is None:
            self.epoch += 1
            self.stats.epochs += 1
            self.offset = 0
            return self._accept(float(raw), raw, FLAG_EPOCH_START, payload)
        t = float(raw + self.offset)
        d1 = t - self.prev_t
        if d1 == 0:
            self.stats.duplicates += 1
            self.invalid_since_prev += 1
            return self._reject(payload, raw, t, FLAG_DUPLICATE)
        big = BIG_JUMP_FACTOR * med
        if 0 < d1 <= big:
            return self._accept(t, raw, self._gap(d1, med), payload)
        next_raw = following[1] if following is not None else None
        if next_raw is not None:
            dn = float(next_raw + self.offset) - self.prev_t
            if 0 < dn <= self.max_factor * med:
                self.stats.glitches += 1
                self.invalid_since_prev += 1
                return self._reject(payload, raw, None, FLAG_GLITCH)
        if d1 < 0:
            prev_raw = self.prev_raw if self.prev_raw is not None else 0
            continues = next_raw is None or 0 < next_raw - raw <= big
            if prev_raw > WRAP_US - WRAP_GUARD_US and raw < WRAP_GUARD_US and continues:
                self.offset += WRAP_US
                self.stats.wraps += 1
                t = float(raw + self.offset)
                flags = FLAG_WRAP | self._gap(t - self.prev_t, med)
                return self._accept(t, raw, flags, payload)
            if -d1 < RESET_MIN_BACKWARD_US and raw >= RESET_BOOT_WINDOW_US:
                self.stats.backward_steps += 1
                self.invalid_since_prev += 1
                return self._reject(payload, raw, t, FLAG_BACKWARD)
            self.stats.resets += 1
            self.epoch += 1
            self.stats.epochs += 1
            self.offset = 0
            self.prev_t = None
            return self._accept(float(raw), raw, FLAG_EPOCH_START, payload)
        return self._accept(t, raw, self._gap(d1, med), payload)


@dataclass
class TimestampAnalysis:
    flags: np.ndarray
    epoch: np.ndarray
    t_us: np.ndarray
    median_interval_us: float
    stats: TimestampStats
    epoch_summary: list[dict] = field(default_factory=list)

    @property
    def good_mask(self) -> np.ndarray:
        return (self.flags & EXCLUDED_FLAGS) == 0

    def fs_median_hz(self) -> float | None:
        return 1e6 / self.median_interval_us if self.median_interval_us > 0 else None

    def fs_mean_hz(self) -> float | None:
        count = sum(max(0, e["good"] - 1) for e in self.epoch_summary)
        span = sum(e["span_us"] for e in self.epoch_summary)
        return count / (span / 1e6) if span > 0 else None

    def duration_s(self) -> float:
        return sum(e["span_us"] for e in self.epoch_summary) / 1e6


def robust_median_interval(t_raw: np.ndarray) -> float:
    if len(t_raw) < 2:
        return DEFAULT_INTERVAL_US
    diffs = np.diff(t_raw.astype(np.float64))
    positive = diffs[(diffs > 0) & (diffs < 5e6)]
    if len(positive) == 0:
        return DEFAULT_INTERVAL_US
    return float(np.median(positive))


def classify_timestamps(t_raw: np.ndarray, valid: np.ndarray | None = None, max_factor: float = 3.0) -> TimestampAnalysis:
    n = len(t_raw)
    flags = np.zeros(n, dtype=np.uint8)
    epoch = np.full(n, -1, dtype=np.int32)
    t_us = np.full(n, np.nan, dtype=np.float64)
    if valid is None:
        valid = np.ones(n, dtype=bool)
    flags[~valid] |= FLAG_INVALID
    idx = np.flatnonzero(valid)
    median = robust_median_interval(t_raw[idx]) if len(idx) else DEFAULT_INTERVAL_US
    clf = TimestampClassifier(fixed_median_us=median, max_factor=max_factor)
    decisions: list[Decision] = []
    for i in idx:
        decisions.extend(clf.push(int(i), int(t_raw[i])))
    decisions.extend(clf.flush())
    for d in decisions:
        flags[d.payload] |= d.flags
        epoch[d.payload] = d.epoch
        if d.t_us is not None:
            t_us[d.payload] = d.t_us
    summary = []
    good = (flags & EXCLUDED_FLAGS) == 0
    for e in range(clf.stats.epochs):
        members = np.flatnonzero((epoch == e) & good)
        if len(members) == 0:
            continue
        span = float(t_us[members[-1]] - t_us[members[0]])
        summary.append({"epoch": e, "first_row": int(members[0]), "last_row": int(members[-1]), "good": int(len(members)), "span_us": span})
    return TimestampAnalysis(flags=flags, epoch=epoch, t_us=t_us, median_interval_us=median, stats=clf.stats, epoch_summary=summary)
