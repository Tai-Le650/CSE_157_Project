from __future__ import annotations

import csv
import io
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..api.errors import AppError

AXES = ("ax", "ay", "az", "gx", "gy", "gz")
TIME_FACTORS_US = {"us": 1.0, "ms": 1e3, "s": 1e6}
MICROSECOND_ALIASES = ("t_us", "time_us")
HOST_COLUMN = "host_rx_ns"
UNITS = {"accel": "g", "gyro": "deg/s"}


@dataclass
class ImuTable:
    t_raw: np.ndarray
    t_us: np.ndarray
    values: np.ndarray
    valid_rows: np.ndarray
    header_alias: str
    time_unit: str
    rows_total: int
    host_ns: np.ndarray | None = None
    segment: np.ndarray | None = None
    epoch: np.ndarray | None = None
    row_issues: Counter = field(default_factory=Counter)
    issue_examples: list = field(default_factory=list)
    extra_columns: list = field(default_factory=list)
    header: list = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.t_us)

    def good_samples_array(self) -> np.ndarray:
        mask = self.valid_rows
        return np.column_stack([self.t_us[mask], self.values[mask]])


def decode_csv(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _parse_float(text: str) -> tuple[float, str | None]:
    stripped = text.strip()
    if stripped == "":
        return math.nan, "missing_value"
    try:
        value = float(stripped)
    except ValueError:
        return math.nan, "non_numeric"
    if not math.isfinite(value):
        return math.nan, "non_finite"
    return value, None


def resolve_time_column(header: list[str], time_unit: str | None) -> tuple[str, str]:
    for alias in MICROSECOND_ALIASES:
        if alias in header:
            if time_unit not in (None, "us"):
                raise AppError("time_unit_conflict", f"Column '{alias}' is defined in microseconds; do not supply another unit", 422)
            return alias, "us"
    if "time" in header:
        if time_unit not in TIME_FACTORS_US:
            raise AppError(
                "time_unit_required",
                "This file has a 'time' column. Choose its unit explicitly (s, ms or us); it is never guessed.",
                422,
                {"accepted_units": list(TIME_FACTORS_US)},
            )
        return "time", time_unit
    raise AppError("missing_time_column", "Expected a timestamp column named t_us, time_us, or time (with an explicit unit)", 422, {"header": header})


def read_imu_csv(source: Path | bytes | str, time_unit: str | None = None, max_examples: int = 20) -> ImuTable:
    if isinstance(source, Path):
        text = decode_csv(source.read_bytes())
    elif isinstance(source, bytes):
        text = decode_csv(source)
    else:
        text = source
    reader = csv.reader(io.StringIO(text))
    try:
        raw_header = next(reader)
    except StopIteration:
        raise AppError("empty_file", "The CSV file is empty", 422)
    header = [h.strip().lower() for h in raw_header]
    missing = [axis for axis in AXES if axis not in header]
    time_column, unit = resolve_time_column(header, time_unit)
    if missing:
        raise AppError("missing_columns", f"Missing required columns: {', '.join(missing)}", 422, {"missing": missing, "header": header})
    t_index = header.index(time_column)
    axis_index = [header.index(axis) for axis in AXES]
    host_index = header.index(HOST_COLUMN) if HOST_COLUMN in header else None
    segment_index = header.index("segment") if "segment" in header else None
    epoch_index = header.index("epoch") if "epoch" in header else None
    known = {time_column, *AXES, HOST_COLUMN, "segment", "epoch"}
    extra = [h for h in header if h not in known]
    times: list[float] = []
    rows: list[list[float]] = []
    hosts: list[float] = []
    segments: list[float] = []
    epochs: list[float] = []
    valid: list[bool] = []
    issues: Counter = Counter()
    examples: list[dict] = []
    for line_number, row in enumerate(reader, start=2):
        if not row or all(not cell.strip() for cell in row):
            continue
        reason = None
        if len(row) < len(header):
            reason = "field_count"
            row = row + [""] * (len(header) - len(row))
        t_value, t_reason = _parse_float(row[t_index])
        values = []
        value_reason = None
        for index in axis_index:
            value, problem = _parse_float(row[index])
            values.append(value)
            if problem and value_reason is None:
                value_reason = problem
        reason = reason or t_reason or value_reason
        if t_reason is None and t_value < 0:
            reason = reason or "bad_timestamp"
            t_value = math.nan
        times.append(t_value)
        rows.append(values)
        if host_index is not None:
            hosts.append(_parse_float(row[host_index])[0])
        if segment_index is not None:
            segments.append(_parse_float(row[segment_index])[0])
        if epoch_index is not None:
            epochs.append(_parse_float(row[epoch_index])[0])
        valid.append(reason is None)
        if reason is not None:
            issues[reason] += 1
            if len(examples) < max_examples:
                examples.append({"line": line_number, "reason": reason, "text": ",".join(row)[:160]})
    t_raw = np.asarray(times, dtype=np.float64)
    values_array = np.asarray(rows, dtype=np.float64).reshape(-1, 6)
    return ImuTable(
        t_raw=t_raw,
        t_us=t_raw * TIME_FACTORS_US[unit],
        values=values_array,
        valid_rows=np.asarray(valid, dtype=bool),
        header_alias=time_column,
        time_unit=unit,
        rows_total=len(times),
        host_ns=np.asarray(hosts, dtype=np.float64) if host_index is not None else None,
        segment=np.asarray(segments, dtype=np.float64) if segment_index is not None else None,
        epoch=np.asarray(epochs, dtype=np.float64) if epoch_index is not None else None,
        row_issues=issues,
        issue_examples=examples,
        extra_columns=extra,
        header=header,
    )


def magnitude(values: np.ndarray, which: str) -> np.ndarray:
    block = values[:, 0:3] if which == "accel" else values[:, 3:6]
    return np.sqrt(np.sum(block * block, axis=1))


CHANNELS = ("ax", "ay", "az", "gx", "gy", "gz", "amag", "gmag")


def channel_values(values: np.ndarray, channel: str) -> np.ndarray:
    if channel in AXES:
        return values[:, AXES.index(channel)]
    if channel == "amag":
        return magnitude(values, "accel")
    if channel == "gmag":
        return magnitude(values, "gyro")
    raise AppError("unknown_channel", f"Unknown channel '{channel}'", 422, {"channels": list(CHANNELS)})


def channel_unit(channel: str) -> str:
    return UNITS["accel"] if channel in ("ax", "ay", "az", "amag") else UNITS["gyro"]
