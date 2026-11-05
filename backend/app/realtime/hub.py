from __future__ import annotations

import asyncio
import itertools
import json
import math
import threading
import time
import uuid
from collections import deque
from typing import Any, Callable

import numpy as np

PROTOCOL_VERSION = 1
KNOWN_TOPIC_PREFIXES = {
    "status",
    "connections",
    "samples",
    "spectra",
    "predictions",
    "detections",
    "actions",
    "training",
    "log",
    "recorder",
    "sound",
    "cursor",
    "sync",
}


def clean(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (np.floating,)):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.ndarray):
        return [clean(v) for v in value.tolist()]
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, deque)):
        return [clean(v) for v in value]
    return value


def to_json(payload: Any) -> str:
    return json.dumps(clean(payload), separators=(",", ":"), allow_nan=False)


def topic_is_valid(topic: str) -> bool:
    prefix = topic.split(":", 1)[0]
    return prefix in KNOWN_TOPIC_PREFIXES and len(topic) <= 80


class ClientConnection:
    def __init__(self, client_id: str, websocket: Any, frame_capacity: int):
        self.client_id = client_id
        self.websocket = websocket
        self.topics: set[str] = set()
        self.priority: deque[str] = deque()
        self.frames: deque[str] = deque()
        self.frame_capacity = frame_capacity
        self.wakeup = asyncio.Event()
        self.last_heartbeat = time.monotonic()
        self.connected_at = time.time()
        self.frames_dropped = 0
        self.closed = False

    def wants(self, topic: str) -> bool:
        if topic in self.topics:
            return True
        prefix = topic.split(":", 1)[0]
        return f"{prefix}:*" in self.topics

    def offer(self, text: str, droppable: bool) -> bool:
        dropped = False
        if droppable:
            if len(self.frames) >= self.frame_capacity:
                self.frames.popleft()
                self.frames_dropped += 1
                dropped = True
            self.frames.append(text)
        else:
            self.priority.append(text)
        self.wakeup.set()
        return dropped


class Hub:
    def __init__(self, flush_interval_s: float = 0.05, frame_capacity: int = 40):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: dict[str, ClientConnection] = {}
        self._seq = itertools.count(1)
        self._lock = threading.Lock()
        self._pending: dict[str, list] = {}
        self._pending_meta: dict[str, dict] = {}
        self._flush_task: asyncio.Task | None = None
        self.flush_interval_s = flush_interval_s
        self.frame_capacity = frame_capacity
        self.ui_frames_dropped = 0
        self.ui_samples_dropped = 0
        self.snapshot_provider: Callable[[], dict] | None = None
        self.close_listeners: list[Callable[[str], None]] = []
        self.heartbeat_listeners: list[Callable[[str], None]] = []

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def client_ids(self) -> list[str]:
        return list(self._clients)

    def has_client(self, client_id: str) -> bool:
        return client_id in self._clients

    def last_heartbeat(self, client_id: str) -> float | None:
        conn = self._clients.get(client_id)
        return conn.last_heartbeat if conn else None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def stop(self) -> None:
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        for conn in list(self._clients.values()):
            conn.closed = True
            conn.wakeup.set()
        self._loop = None

    def envelope(self, topic: str, type_: str, data: Any) -> dict:
        return {"v": PROTOCOL_VERSION, "type": type_, "topic": topic, "seq": next(self._seq), "ts": time.time(), "data": data}

    def publish(self, topic: str, type_: str, data: Any) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        text = to_json(self.envelope(topic, type_, data))
        try:
            loop.call_soon_threadsafe(self._fanout, topic, text, False)
        except RuntimeError:
            pass

    def _fanout(self, topic: str, text: str, droppable: bool) -> None:
        for conn in list(self._clients.values()):
            if conn.closed or not conn.wants(topic):
                continue
            if conn.offer(text, droppable):
                self.ui_frames_dropped += 1

    def push_samples(self, sensor_id: str, rows: list, meta: dict) -> None:
        if self._loop is None:
            return
        with self._lock:
            pending = self._pending.setdefault(sensor_id, [])
            pending.extend(rows)
            overflow = len(pending) - 4000
            if overflow > 0:
                del pending[:overflow]
                self.ui_samples_dropped += overflow
            self._pending_meta[sensor_id] = meta

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(self.flush_interval_s)
            with self._lock:
                batches = self._pending
                metas = self._pending_meta
                self._pending = {}
                self._pending_meta = {}
            for sensor_id, rows in batches.items():
                if not rows:
                    continue
                topic = f"samples:{sensor_id}"
                if not any(c.wants(topic) for c in self._clients.values()):
                    continue
                data = {
                    "sensor_id": sensor_id,
                    "simulated": bool(metas.get(sensor_id, {}).get("simulated", False)),
                    "epoch": rows[-1][1],
                    "t_us": [r[0] for r in rows],
                    "ax": [r[2] for r in rows],
                    "ay": [r[3] for r in rows],
                    "az": [r[4] for r in rows],
                    "gx": [r[5] for r in rows],
                    "gy": [r[6] for r in rows],
                    "gz": [r[7] for r in rows],
                }
                text = json.dumps(self.envelope(topic, "samples", data), separators=(",", ":"))
                self._fanout(topic, text, True)

    async def register(self, websocket: Any) -> ClientConnection:
        client_id = uuid.uuid4().hex[:12]
        conn = ClientConnection(client_id, websocket, self.frame_capacity)
        self._clients[client_id] = conn
        snapshot = self.snapshot_provider() if self.snapshot_provider else {}
        hello = self.envelope("status", "hello", {"client_id": client_id, "protocol": PROTOCOL_VERSION, "snapshot": snapshot})
        conn.offer(to_json(hello), False)
        return conn

    def unregister(self, client_id: str) -> None:
        conn = self._clients.pop(client_id, None)
        if conn is None:
            return
        conn.closed = True
        conn.wakeup.set()
        for listener in list(self.close_listeners):
            try:
                listener(client_id)
            except Exception:
                pass

    def heartbeat(self, client_id: str) -> None:
        conn = self._clients.get(client_id)
        if conn is None:
            return
        conn.last_heartbeat = time.monotonic()
        for listener in list(self.heartbeat_listeners):
            try:
                listener(client_id)
            except Exception:
                pass

    async def sender(self, conn: ClientConnection) -> None:
        while not conn.closed:
            await conn.wakeup.wait()
            conn.wakeup.clear()
            while not conn.closed and (conn.priority or conn.frames):
                text = conn.priority.popleft() if conn.priority else conn.frames.popleft()
                await conn.websocket.send_text(text)
