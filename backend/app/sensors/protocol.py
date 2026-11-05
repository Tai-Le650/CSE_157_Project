from __future__ import annotations

import math
import re
from dataclasses import dataclass

MAX_LINE_BYTES = 256
AXES = ("ax", "ay", "az", "gx", "gy", "gz")
TIME_ALIASES = ("t_us", "time_us")
ASCII_DIGITS = re.compile(r"^[0-9]+$")
NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


@dataclass(slots=True)
class ParsedLine:
    kind: str
    text: str
    t_raw: int | None = None
    values: tuple[float, float, float, float, float, float] | None = None
    alias: str | None = None
    reason: str | None = None
    is_error: bool = False


class LineAssembler:
    def __init__(self, sync_first_line: bool = True, max_line_bytes: int = MAX_LINE_BYTES):
        self.buffer = bytearray()
        self.synced = not sync_first_line
        self.max_line_bytes = max_line_bytes
        self.partial_dropped = 0
        self.overflows = 0

    def feed(self, data: bytes) -> list[bytes]:
        if data:
            self.buffer.extend(data)
        lines: list[bytes] = []
        while True:
            index = self.buffer.find(b"\n")
            if index < 0:
                if len(self.buffer) > self.max_line_bytes:
                    self.buffer.clear()
                    self.overflows += 1
                    self.synced = False
                break
            line = bytes(self.buffer[:index])
            del self.buffer[: index + 1]
            if not self.synced:
                self.synced = True
                text = line.decode("utf-8", errors="replace").strip()
                if parse_header(text) is not None:
                    lines.append(line)
                elif text:
                    self.partial_dropped += 1
                continue
            if len(line) > self.max_line_bytes:
                self.overflows += 1
                continue
            lines.append(line)
        return lines


def parse_header(text: str) -> str | None:
    parts = [p.strip().lower() for p in text.split(",")]
    if len(parts) == 7 and parts[0] in TIME_ALIASES and tuple(parts[1:]) == AXES:
        return parts[0]
    return None


def parse_line(raw: bytes | str) -> ParsedLine:
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else raw
    text = text.strip().strip("\x00")
    if not text:
        return ParsedLine("empty", text)
    alias = parse_header(text)
    if alias is not None:
        return ParsedLine("header", text, alias=alias)
    parts = text.split(",")
    if len(parts) == 7:
        stamp = parts[0].strip()
        if not ASCII_DIGITS.match(stamp):
            if NUMBER.match(stamp):
                return ParsedLine("malformed", text, reason="bad_timestamp")
            return ParsedLine("diagnostic", text, is_error=text.upper().startswith("ERROR"))
        values: list[float] = []
        for part in parts[1:]:
            part = part.strip()
            try:
                value = float(part)
            except ValueError:
                return ParsedLine("malformed", text, reason="non_numeric")
            values.append(value)
        if not all(math.isfinite(v) for v in values):
            return ParsedLine("malformed", text, reason="non_finite")
        return ParsedLine("sample", text, t_raw=int(stamp), values=tuple(values))
    if any(ch.isalpha() for ch in text):
        return ParsedLine("diagnostic", text, is_error=text.upper().startswith("ERROR"))
    return ParsedLine("malformed", text, reason="field_count")
