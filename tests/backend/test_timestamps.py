from __future__ import annotations

import numpy as np

from app.processing.timestamps import (
    FLAG_DUPLICATE,
    FLAG_EPOCH_START,
    FLAG_GAP_BEFORE,
    FLAG_GLITCH,
    FLAG_WRAP,
    TimestampClassifier,
    classify_timestamps,
)

DT = 9614


def series(n, start=362_952_019, dt=DT):
    return [start + i * dt for i in range(n)]


def test_isolated_truncated_timestamp_is_glitch_not_reset():
    t = series(200)
    t[120] = int(str(t[120])[3:])
    analysis = classify_timestamps(np.array(t, dtype=np.float64))
    assert analysis.stats.glitches == 1
    assert analysis.stats.resets == 0
    assert analysis.stats.epochs == 1
    assert analysis.flags[120] & FLAG_GLITCH
    assert analysis.stats.gaps == 0
    assert analysis.stats.estimated_missing == 0
    assert analysis.good_mask.sum() == 199
    assert abs(analysis.fs_median_hz() - 1e6 / DT) < 0.01


def test_gap_counts_estimated_missing():
    t = series(100)
    del t[50:53]
    analysis = classify_timestamps(np.array(t, dtype=np.float64))
    assert analysis.stats.gaps == 1
    assert analysis.stats.estimated_missing == 3
    assert analysis.flags[50] & FLAG_GAP_BEFORE


def test_duplicates_are_flagged_and_excluded():
    t = series(50)
    t.insert(20, t[19])
    analysis = classify_timestamps(np.array(t, dtype=np.float64))
    assert analysis.stats.duplicates == 1
    assert analysis.flags[20] & FLAG_DUPLICATE
    assert not analysis.good_mask[20]


def test_32bit_micros_wrap_is_unwrapped():
    start = (1 << 32) - 30 * DT
    t = [(start + i * DT) % (1 << 32) for i in range(80)]
    analysis = classify_timestamps(np.array(t, dtype=np.float64))
    assert analysis.stats.wraps == 1
    assert analysis.stats.resets == 0
    wrap_index = int(np.flatnonzero(analysis.flags & FLAG_WRAP)[0])
    assert wrap_index == 30
    assert np.all(np.diff(analysis.t_us) > 0)


def test_clock_reset_starts_new_epoch():
    t = series(60) + series(60, start=1_000_000)
    analysis = classify_timestamps(np.array(t, dtype=np.float64))
    assert analysis.stats.resets == 1
    assert analysis.stats.epochs == 2
    assert analysis.flags[60] & FLAG_EPOCH_START
    assert len(analysis.epoch_summary) == 2


def test_live_classifier_matches_offline():
    t = series(300)
    t[100] = int(str(t[100])[2:])
    del t[200:202]
    t[250] = t[249]
    offline = classify_timestamps(np.array(t, dtype=np.float64))
    live = TimestampClassifier()
    flags = {}
    for i, stamp in enumerate(t):
        for decision in live.push(i, stamp):
            flags[decision.payload] = decision.flags
    for decision in live.flush():
        flags[decision.payload] = decision.flags
    live_flags = np.array([flags[i] for i in range(len(t))], dtype=np.uint8)
    assert np.array_equal(live_flags[10:], offline.flags[10:])
    assert live.stats.glitches == offline.stats.glitches == 1
    assert live.stats.duplicates == offline.stats.duplicates == 1
    assert live.stats.estimated_missing == offline.stats.estimated_missing == 2


def test_small_backward_step_is_out_of_order_not_reset():
    t = series(100)
    t.insert(60, t[58])
    analysis = classify_timestamps(np.array(t, dtype=np.float64))
    assert analysis.stats.resets == 0
    assert analysis.stats.epochs == 1
    assert analysis.stats.backward_steps + analysis.stats.duplicates + analysis.stats.glitches >= 1
    assert analysis.good_mask.sum() == 100


def test_return_to_boot_time_is_reset():
    t = series(50) + series(50, start=400_000)
    analysis = classify_timestamps(np.array(t, dtype=np.float64))
    assert analysis.stats.resets == 1
