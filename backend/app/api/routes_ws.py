from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..realtime.hub import topic_is_valid, to_json
from .security import origin_matches_host, websocket_allowed

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    origin = websocket.headers.get("origin")
    token = websocket.query_params.get("token")
    registry = getattr(websocket.app.state, "sandboxes", None)
    sandbox = None
    if registry is not None:
        if origin is not None and not origin_matches_host(origin, websocket.headers.get("host")):
            await websocket.close(code=1008, reason="origin_rejected")
            return
        sandbox = registry.lookup(token)
        if sandbox is None:
            await websocket.close(code=1008, reason="invalid_session_token")
            return
        container = sandbox.container
    else:
        container = websocket.app.state.container
        allowed, reason = websocket_allowed(origin, token, container.config.allowed_origins, container.config.session_token)
        if not allowed:
            await websocket.close(code=1008, reason=reason)
            return
    await websocket.accept()
    if sandbox is not None:
        sandbox.sockets.add(websocket)
    hub = container.hub
    conn = await hub.register(websocket)
    sender = asyncio.create_task(hub.sender(conn))
    try:
        while True:
            text = await websocket.receive_text()
            try:
                message = json.loads(text)
            except ValueError:
                conn.offer(to_json(hub.envelope("status", "error", {"code": "bad_json", "message": "Messages must be JSON"})), False)
                continue
            if not isinstance(message, dict):
                continue
            kind = message.get("type")
            if kind == "subscribe":
                topics = [t for t in message.get("topics", []) if isinstance(t, str) and topic_is_valid(t)]
                conn.topics.update(topics)
                conn.offer(to_json(hub.envelope("status", "subscribed", {"topics": sorted(conn.topics)})), False)
            elif kind == "unsubscribe":
                for topic in message.get("topics", []):
                    conn.topics.discard(topic)
                conn.offer(to_json(hub.envelope("status", "subscribed", {"topics": sorted(conn.topics)})), False)
            elif kind == "heartbeat":
                hub.heartbeat(conn.client_id)
            elif kind == "estop":
                await asyncio.to_thread(container.control.emergency_stop, f"websocket:{conn.client_id}")
            elif kind == "ping":
                conn.offer(to_json(hub.envelope("status", "pong", {"client_id": conn.client_id})), False)
            else:
                conn.offer(to_json(hub.envelope("status", "error", {"code": "unknown_message", "message": f"Unknown message type {kind!r}"})), False)
    except WebSocketDisconnect:
        pass
    except RuntimeError:
        pass
    finally:
        hub.unregister(conn.client_id)
        sender.cancel()
        try:
            await sender
        except (asyncio.CancelledError, Exception):
            pass
        if sandbox is not None:
            sandbox.sockets.discard(websocket)
            sandbox.touch()
