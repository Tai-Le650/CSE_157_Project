from __future__ import annotations

import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any, Callable

from ..processing.timestamps import EXCLUDED_FLAGS, Decision, TimestampClassifier
from .protocol import LineAssembler, parse_line


@dataclass(slots=True)
class Sample:
    t_raw: int
    t_us: float | None
    epoch: int
    host_ns: int
    values: tuple
    flags: int

    @property
    def good(self) -> bool:
        return not (self.flags & EXCLUDED_FLAGS)


@dataclass
class StreamCounters:
    lines_total: int = 0
    bytes_total: int = 0
    samples_parsed: int = 0
    headers: int = 0
    diagnostics: int = 0
    device_errors: int = 0
    malformed: Counter = field(default_factory=Counter)
    rejected_examples: deque = field(default_factory=lambda: deque(maxlen=20))
    last_diagnostic: str | None = None

    def as_dict(self) -> dict:
        return {
            "lines_total": self.lines_total,
            "bytes_total": self.bytes_total,
            "samples_parsed": self.samples_parsed,
            "headers": self.headers,
            "diagnostics": self.diagnostics,
            "device_errors": self.device_errors,
            "malformed_total": sum(self.malformed.values()),
            "malformed": dict(self.malformed),
            "last_diagnostic": self.last_diagnostic,
        }


def describe_serial_error(exc: BaseException) -> dict:
    text = str(exc)
    lowered = text.lower()
    if isinstance(exc, PermissionError) or "permissionerror" in lowered or "access is denied" in lowered:
        code = "port_in_use"
        hint = "The port is open in another program (Arduino Serial Monitor/Plotter or a CLI script). Close it and retry."
    elif isinstance(exc, FileNotFoundError) or "filenotfounderror" in lowered or "cannot find the file" in lowered:
        code = "port_not_found"
        hint = "The port no longer exists. Check the USB cable and refresh the port list."
    else:
        code = "io_error"
        hint = "The serial connection failed. Check the cable and that the board is powered."
    return {"code": code, "message": text[:300], "hint": hint}


class StreamReader(threading.Thread):
    def __init__(
        self,
        sensor_id: str,
        opener: Callable[[], Any],
        on_samples: Callable[[str, list[Sample]], None],
        on_event: Callable[[str, str, dict], None],
        batch_interval_s: float = 0.02,
    ):
        super().__init__(name=f"stream-{sensor_id}", daemon=True)
        self.sensor_id = sensor_id
        self.opener = opener
        self.on_samples = on_samples
        self.on_event = on_event
        self.batch_interval_s = batch_interval_s
        self.stop_event = threading.Event()
        self.counters = StreamCounters()
        self.classifier = TimestampClassifier()
        self.assembler = LineAssembler()
        self.header_alias: str | None = None
        self.port: Any = None
        self.opened_at: float | None = None

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        try:
            self.port = self.opener()
        except Exception as exc:
            self.on_event(self.sensor_id, "open_failed", {"error": describe_serial_error(exc)})
            return
        self.opened_at = time.time()
        self.on_event(self.sensor_id, "opened", {})
        batch: list[Sample] = []
        last_flush = time.perf_counter()
        lost: dict | None = None
        try:
            while not self.stop_event.is_set():
                try:
                    waiting = self.port.in_waiting
                    data = self.port.read(waiting if waiting else 1)
                except Exception as exc:
                    lost = describe_serial_error(exc)
                    break
                host_ns = time.perf_counter_ns()
                if data:
                    self.counters.bytes_total += len(data)
                    for line in self.assembler.feed(data):
                        self._handle_line(line, host_ns, batch)
                now = time.perf_counter()
                if batch and (now - last_flush >= self.batch_interval_s or len(batch) >= 64):
                    self.on_samples(self.sensor_id, batch)
                    batch = []
                    last_flush = now
        finally:
            for decision in self.classifier.flush():
                batch.append(self._to_sample(decision))
            if batch:
                self.on_samples(self.sensor_id, batch)
            try:
                self.port.close()
            except Exception:
                pass
            if lost is not None:
                self.on_event(self.sensor_id, "lost", {"error": lost})
            else:
                self.on_event(self.sensor_id, "closed", {})

    def _handle_line(self, line: bytes, host_ns: int, batch: list[Sample]) -> None:
        self.counters.lines_total += 1
        parsed = parse_line(line)
        if parsed.kind == "sample":
            self.counters.samples_parsed += 1
            for decision in self.classifier.push((host_ns, parsed.values), parsed.t_raw):
                batch.append(self._to_sample(decision))
        elif parsed.kind == "header":
            self.counters.headers += 1
            for decision in self.classifier.start_new_epoch():
                batch.append(self._to_sample(decision))
            self.header_alias = parsed.alias
            self.on_event(self.sensor_id, "header", {"alias": parsed.alias})
        elif parsed.kind == "diagnostic":
            self.counters.diagnostics += 1
            self.counters.last_diagnostic = parsed.text[:200]
            if parsed.is_error:
                self.counters.device_errors += 1
            self.on_event(self.sensor_id, "diagnostic", {"text": parsed.text[:200], "is_error": parsed.is_error})
        elif parsed.kind == "malformed":
            self.counters.malformed[parsed.reason or "unknown"] += 1
            self.counters.rejected_examples.append({"reason": parsed.reason, "text": parsed.text[:120]})

    def _to_sample(self, decision: Decision) -> Sample:
        host_ns, values = decision.payload
        return Sample(decision.t_raw, decision.t_us, decision.epoch, host_ns, values, decision.flags)

    def partial_lines_dropped(self) -> int:
        return self.assembler.partial_dropped

    def overflows(self) -> int:
        return self.assembler.overflows
