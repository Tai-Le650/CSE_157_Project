from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.processing.csv_io import channel_values, read_imu_csv
from app.processing.repair import PRESETS, RepairRecipe, RepairStep, apply_recipe
from app.processing.spectral import analyze_uniform
from conftest import FIXTURES, REFERENCE_RECORDINGS


def test_default_recipe_drops_only_glitch_rows():
    table = read_imu_csv(FIXTURES / "glitch.csv")
    result = apply_recipe(table, PRESETS["default-v1"])
    assert result.n == table.n - 2
    ops = {c["op"]: c for c in result.step_counts}
    assert ops["drop_timestamp_glitches"]["removed"] == 2
    assert ops["drop_timestamp_glitches"]["glitches"] == 2
    assert np.all(np.diff(result.t_us) > 0)
    assert not result.uniform


def test_legacy_recipe_keeps_longest_monotonic_run():
    table = read_imu_csv(FIXTURES / "glitch.csv")
    result = apply_recipe(table, PRESETS["legacy-analyze-v1"])
    seg = next(c for c in result.step_counts if c["op"] == "segments")
    assert seg["backward_steps"] == 2
    assert seg["rows_after"] == 120
    assert result.uniform


def test_resets_split_without_sorting():
    table = read_imu_csv(FIXTURES / "reset.csv")
    result = apply_recipe(table, PRESETS["default-v1"])
    assert result.n == 200
    assert list(np.unique(result.epoch)) == [0, 1]
    assert result.t_us[0] == table.t_us[0]
    assert result.t_us[100] == table.t_us[100]
    first_epoch_last = result.t_us[99]
    assert result.t_us[100] < first_epoch_last


def test_wrap_is_unwrapped_and_gaps_split():
    wrap = apply_recipe(read_imu_csv(FIXTURES / "wrap.csv"), PRESETS["default-v1"])
    assert np.all(np.diff(wrap.t_us) > 0)
    assert next(c for c in wrap.step_counts if c["op"] == "unwrap_micros")["wraps"] == 1
    gaps = apply_recipe(read_imu_csv(FIXTURES / "gaps.csv"), PRESETS["default-resampled-v1"])
    gap_step = next(c for c in gaps.step_counts if c["op"] == "gaps")
    assert gap_step["splits"] == 1
    assert gaps.uniform
    for start, end in gaps.segments():
        steps = np.diff(gaps.t_us[start:end])
        assert np.allclose(steps, steps[0], atol=1e-6)


def test_custom_recipe_validation():
    recipe = RepairRecipe(name="mine", steps=[RepairStep(op="drop_invalid_rows"), RepairStep(op="resample", target_hz=100)])
    result = apply_recipe(read_imu_csv(FIXTURES / "bad_values.csv"), recipe)
    assert result.fs_hz == 100
    assert result.step_counts[0]["removed"] == 5


def test_sine_spectrum_peak():
    fs = 100.0
    t = np.arange(0, 4, 1 / fs)
    x = np.sin(2 * np.pi * 5 * t)
    out = analyze_uniform(x, fs, 128, 32)
    assert abs(out["fft"]["dominant_hz"] - 5.0) <= fs / 128
    assert len(out["stft"]["time_s"]) == (len(x) - 128) // 32 + 1


@pytest.mark.reference
def test_fft_stft_match_imu_capture_outputs():
    plots = REFERENCE_RECORDINGS.parent / "plots" / "swipe_left" / "gx"
    if not (plots / "fft_data.csv").is_file():
        pytest.skip("imu_capture analysis outputs not present")
    result = apply_recipe(read_imu_csv(REFERENCE_RECORDINGS / "swipe_left.csv"), PRESETS["legacy-analyze-v1"])
    out = analyze_uniform(channel_values(result.values, "gx"), result.fs_hz, 128, 32)
    fft_ref = pd.read_csv(plots / "fft_data.csv")
    stft_ref = pd.read_csv(plots / "stft_data_db.csv")
    assert np.allclose(out["fft"]["frequency_hz"], fft_ref.frequency_hz.values, atol=1e-9)
    assert np.allclose(out["fft"]["magnitude"], fft_ref.magnitude.values, atol=1e-9)
    assert np.allclose(np.array(out["stft"]["db"]).T, stft_ref.drop(columns=["time_s"]).values, atol=1e-6)
