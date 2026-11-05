from __future__ import annotations

import time

from fastapi import APIRouter, Query

from ..container import APP_NAME, APP_VERSION
from ..schemas.system import ActivityEntry, HealthOut, PortOut, SessionOut, StatusOut
from ..sensors.ports import list_serial_ports
from .deps import Container
from .security import TOKEN_HEADER

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", response_model=HealthOut, summary="Liveness check")
def health() -> dict:
    return {"status": "ok", "app": APP_NAME, "version": APP_VERSION, "time": time.time()}


@router.get("/session", response_model=SessionOut, summary="Per-launch session token for this browser", description="Readable only from allowed origins. Required on every state-changing REST call and on the WebSocket.")
def session(c: Container) -> dict:
    return {"token": c.config.session_token, "header": TOKEN_HEADER, "websocket_path": "/ws", "bind_host": c.config.host}


@router.get("/status", response_model=StatusOut, summary="Current modes and system status")
def status(c: Container) -> dict:
    return c.status()


@router.get("/snapshot", summary="Full state snapshot (same as the WebSocket hello message)")
def snapshot(c: Container) -> dict:
    return c.snapshot()


@router.get("/activity", response_model=list[ActivityEntry], summary="Recent activity log entries")
def activity(c: Container, limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    return c.activity.recent(limit)


@router.get("/ports", response_model=list[PortOut], summary="Discover Windows COM ports", description="Lists serial ports via PySerial. A port shown here may still be busy in another program (Arduino Serial Monitor or a CLI script).")
def ports(c: Container) -> list[dict]:
    owned = c.sensors.owned_ports()
    out = []
    for port in list_serial_ports():
        port["owned_by"] = owned.get(port["device"])
        out.append(port)
    return out
