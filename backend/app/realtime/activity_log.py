from __future__ import annotations

import json
import logging
import logging.handlers
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from .hub import Hub, clean

LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": record.created,
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "activity", None)
        if extra:
            payload["data"] = clean(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(logs_dir: Path | None) -> None:
    root = logging.getLogger("gesture_to_pc")
    root.setLevel(logging.INFO)
    if logs_dir is None:
        return
    logs_dir.mkdir(parents=True, exist_ok=True)
    target = (logs_dir / "backend.log").resolve()
    for handler in root.handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler) and Path(handler.baseFilename) == target:
            return
    handler = logging.handlers.RotatingFileHandler(target, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(JsonLineFormatter())
    root.addHandler(handler)


class ActivityLog:
    def __init__(self, hub: Hub, maxlen: int = 500):
        self._hub = hub
        self._entries: deque[dict] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._counter = 0
        self._logger = logging.getLogger("gesture_to_pc.activity")

    def add(self, level: str, category: str, message: str, **data: Any) -> dict:
        with self._lock:
            self._counter += 1
            entry = {"id": self._counter, "ts": time.time(), "level": level, "category": category, "message": message, "data": clean(data)}
            self._entries.append(entry)
        self._logger.log(LEVELS.get(level, logging.INFO), f"[{category}] {message}", extra={"activity": data})
        self._hub.publish("log", "log", entry)
        return entry

    def info(self, category: str, message: str, **data: Any) -> dict:
        return self.add("info", category, message, **data)

    def warning(self, category: str, message: str, **data: Any) -> dict:
        return self.add("warning", category, message, **data)

    def error(self, category: str, message: str, **data: Any) -> dict:
        return self.add("error", category, message, **data)

    def recent(self, limit: int = 100) -> list[dict]:
        with self._lock:
            items = list(self._entries)
        return items[-limit:]
