from __future__ import annotations

import numpy as np
import pytest

from app.api.errors import AppError
from app.processing.csv_io import read_imu_csv
from app.processing.validation import validate_table
from conftest import FIXTURES


def report_for(name: str, **kw) -> dict:
    report, _ = validate_table(read_imu_csv(FIXTURES / name, **kw))
    return report


def test_both_microsecond_aliases_parse_identically():
    a = read_imu_csv(FIXTURES / "trial_t_us.csv")
    b = read_imu_csv(FIXTURES / "trial_time_us.csv")
    assert a.header_alias == "t_us" and b.header_alias == "time_us"
    assert a.time_unit == b.time_unit == "us"
    assert np.array_equal(a.t_us, b.t_us)
    assert np.array_equal(a.values, b.values)
    assert report_for("trial_t_us.csv")["state"] == "valid"


def test_time_column_requires_explicit_unit():
    with pytest.raises(AppError) as err:
        read_imu_csv(FIXTURES / "trial_time_seconds.csv")
    assert err.value.code == "time_unit_required"
    seconds = read_imu_csv(FIXTURES / "trial_time_seconds.csv", time_unit="s")
    reference = read_imu_csv(FIXTURES / "trial_t_us.csv")
    assert np.allclose(seconds.t_us, reference.t_us - reference.t_us[0], atol=1.0)
    with pytest.raises(AppError) as conflict:
        read_imu_csv(FIXTURES / "trial_t_us.csv", time_unit="s")
    assert conflict.value.code == "time_unit_conflict"


def test_missing_columns_rejected():
    with pytest.raises(AppError) as err:
        read_imu_csv(FIXTURES / "missing_column.csv")
    assert err.value.code == "missing_columns"
    assert err.value.details["missing"] == ["gz"]


def test_invalid_values_counted_by_reason():
    report = report_for("bad_values.csv")
    assert report["state"] == "flagged"
    assert report["rows"]["by_reason"] == {"non_finite": 2, "missing_value": 1, "non_numeric": 1, "field_count": 1}
    assert report["measured_invalid"]["format_rows"] == 5
    assert report["good_samples"] == 75


def test_glitches_are_measured_invalid_not_dropped_samples():
    report = report_for("glitch.csv")
    assert report["state"] == "flagged"
    assert report["timestamps"]["glitches"] == 2
    assert report["timestamps"]["resets"] == 0
    assert report["measured_invalid"]["timestamp_glitches"] == 2
    assert report["estimated_dropped"]["samples"] == 0
    assert report["timestamps"]["epochs"] == 1
    assert abs(report["rates"]["fs_median_hz"] - 1e6 / 9614) < 0.01


def test_wrap_reset_duplicates_and_gaps():
    wrap = report_for("wrap.csv")
    assert wrap["timestamps"]["wraps"] == 1 and wrap["state"] == "flagged"
    reset = report_for("reset.csv")
    assert reset["timestamps"]["resets"] == 1 and reset["timestamps"]["epochs"] == 2
    assert any(i["code"] == "clock_resets" for i in reset["issues"])
    dup = report_for("duplicates.csv")
    assert dup["timestamps"]["duplicates"] == 3
    assert dup["estimated_dropped"]["samples"] == 0
    gaps = report_for("gaps.csv")
    assert gaps["estimated_dropped"]["samples"] == 15
    assert gaps["timestamps"]["gaps"] == 3
    assert any(i["code"] == "large_gaps" for i in gaps["issues"])
    assert gaps["estimated_dropped"]["largest_gap_ms"] > 100


def test_insufficient_samples_invalid():
    report = report_for("short.csv")
    assert report["state"] == "invalid"
    assert any(i["code"] == "insufficient_samples" for i in report["issues"])


@pytest.mark.reference
def test_real_imu_capture_recordings_measured():
    from conftest import REFERENCE_RECORDINGS

    if not REFERENCE_RECORDINGS.is_dir():
        pytest.skip("imu_capture recordings not present")
    expected = {"swipe_left.csv": (3, 13), "swipe_right.csv": (2, 11), "wrist_rotation.csv": (1, 14)}
    for name, (glitches, missing) in expected.items():
        report, _ = validate_table(read_imu_csv(REFERENCE_RECORDINGS / name))
        assert report["timestamps"]["glitches"] == glitches
        assert report["timestamps"]["resets"] == 0
        assert report["estimated_dropped"]["samples"] == missing
        assert abs(report["rates"]["fs_median_hz"] - 104.01) < 0.05
