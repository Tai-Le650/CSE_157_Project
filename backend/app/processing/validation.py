from __future__ import annotations

import numpy as np

from .csv_io import AXES, ImuTable
from .timestamps import EXCLUDED_FLAGS, FLAG_GLITCH, TimestampAnalysis, classify_timestamps

VALIDATION_VERSION = "validation-v1"
DEFAULT_MIN_SAMPLES = 30
MAX_INTERPOLATE_GAP_MS = 50.0


def _issue(code: str, severity: str, message: str, count: int | float | None = None) -> dict:
    return {"code": code, "severity": severity, "message": message, "count": count}


def gap_sizes_ms(analysis: TimestampAnalysis) -> list[float]:
    good = np.flatnonzero((analysis.flags & EXCLUDED_FLAGS) == 0)
    sizes = []
    median = analysis.median_interval_us
    for prev, cur in zip(good[:-1], good[1:]):
        if analysis.epoch[prev] != analysis.epoch[cur]:
            continue
        delta = analysis.t_us[cur] - analysis.t_us[prev]
        if delta > 1.5 * median:
            sizes.append(float(delta / 1000.0))
    return sizes


def value_resolution(values: np.ndarray) -> list[float | None]:
    out: list[float | None] = []
    for i in range(values.shape[1]):
        column = np.unique(np.round(values[:, i], 6))
        steps = np.diff(column)
        steps = steps[steps > 1e-9]
        out.append(float(np.min(steps)) if len(steps) else None)
    return out


def validate_table(table: ImuTable, min_samples: int = DEFAULT_MIN_SAMPLES) -> tuple[dict, TimestampAnalysis]:
    analysis = classify_timestamps(table.t_us, valid=table.valid_rows)
    stats = analysis.stats
    good_mask = analysis.good_mask & table.valid_rows
    good_count = int(good_mask.sum())
    issues: list[dict] = []
    malformed_total = int(sum(table.row_issues.values()))
    if malformed_total:
        detail = ", ".join(f"{k}: {v}" for k, v in sorted(table.row_issues.items()))
        issues.append(_issue("invalid_rows", "repair_required", f"{malformed_total} row(s) have missing, non-numeric, non-finite or short fields ({detail})", malformed_total))
    if stats.duplicates:
        issues.append(_issue("duplicate_timestamps", "repair_required", f"{stats.duplicates} row(s) repeat the previous timestamp", stats.duplicates))
    if stats.glitches:
        issues.append(_issue("timestamp_glitches", "repair_required", f"{stats.glitches} isolated row(s) have an impossible timestamp while their neighbours are continuous (consistent with lost leading characters)", stats.glitches))
    if stats.backward_steps:
        issues.append(_issue("out_of_order_timestamps", "repair_required", f"{stats.backward_steps} row(s) step backward by less than 1 s (not a device reset); they are excluded", stats.backward_steps))
    if stats.resets:
        issues.append(_issue("clock_resets", "repair_required", f"Timestamps restart {stats.resets} time(s) (device reset); the file holds {stats.epochs} separate clock segments", stats.resets))
    if stats.wraps:
        issues.append(_issue("micros_wrap", "repair_required", f"32-bit micros() wrapped {stats.wraps} time(s); unwrapping is required", stats.wraps))
    gaps = gap_sizes_ms(analysis)
    large = [g for g in gaps if g > MAX_INTERPOLATE_GAP_MS]
    if large:
        issues.append(_issue("large_gaps", "repair_required", f"{len(large)} gap(s) longer than {MAX_INTERPOLATE_GAP_MS:.0f} ms (largest {max(large):.0f} ms)", len(large)))
    if gaps and not large:
        issues.append(_issue("small_gaps", "info", f"{len(gaps)} short gap(s), about {stats.estimated_missing} estimated missing sample(s); bridged by interpolation when resampling", len(gaps)))
    if good_count < min_samples:
        issues.append(_issue("insufficient_samples", "error", f"Only {good_count} valid samples (minimum {min_samples})", good_count))
    if good_count == 0:
        issues.append(_issue("no_valid_samples", "error", "No valid samples", 0))
    severities = {i["severity"] for i in issues}
    state = "invalid" if "error" in severities else ("flagged" if "repair_required" in severities else "valid")
    good_values = table.values[good_mask]
    ranges = {}
    if len(good_values):
        for i, axis in enumerate(AXES):
            ranges[axis] = {"min": float(np.min(good_values[:, i])), "max": float(np.max(good_values[:, i]))}
    resolution = value_resolution(good_values) if len(good_values) else [None] * 6
    glitch_rows = (np.flatnonzero(analysis.flags & FLAG_GLITCH) + 2).tolist()[:50]
    report = {
        "version": VALIDATION_VERSION,
        "state": state,
        "issues": issues,
        "columns": {"time": table.header_alias, "time_unit": table.time_unit, "units": {"accel": "g", "gyro": "deg/s"}, "extra": table.extra_columns},
        "rows": {"total": table.rows_total, "valid_format": int(table.valid_rows.sum()), "invalid_format": malformed_total, "by_reason": dict(table.row_issues), "examples": table.issue_examples[:10]},
        "timestamps": {**stats.as_dict(), "glitch_file_lines": glitch_rows, "median_interval_us": analysis.median_interval_us},
        "measured_invalid": {
            "format_rows": malformed_total,
            "duplicate_timestamps": stats.duplicates,
            "timestamp_glitches": stats.glitches,
            "backward_steps": stats.backward_steps,
            "total": malformed_total + stats.duplicates + stats.glitches + stats.backward_steps,
        },
        "estimated_dropped": {"samples": stats.estimated_missing, "gaps": stats.gaps, "gap_total_s": stats.gap_total_us / 1e6, "largest_gap_ms": max(gaps) if gaps else None, "note": "Estimated from timestamp gaps; the firmware sends no sequence numbers"},
        "epochs": analysis.epoch_summary,
        "rates": {"fs_median_hz": analysis.fs_median_hz(), "fs_mean_hz": analysis.fs_mean_hz()},
        "duration_s": analysis.duration_s(),
        "good_samples": good_count,
        "min_samples": min_samples,
        "value_ranges": ranges,
        "value_resolution": dict(zip(AXES, resolution)),
    }
    return report, analysis


def rate_compatibility(rates: list[float | None], tolerance: float = 0.15) -> dict:
    measured = [r for r in rates if r]
    if len(measured) < 2:
        return {"compatible": True, "min_hz": measured[0] if measured else None, "max_hz": measured[0] if measured else None, "tolerance": tolerance}
    low, high = min(measured), max(measured)
    return {"compatible": high / low <= 1 + tolerance, "min_hz": low, "max_hz": high, "tolerance": tolerance}
