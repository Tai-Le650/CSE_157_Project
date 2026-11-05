from __future__ import annotations

import time

from fastapi import APIRouter, Query, Request

from ..container import APP_NAME, APP_VERSION
from ..schemas.system import ActivityEntry, HealthOut, PortOut, SessionOut, StatusOut
from ..sensors.ports import list_serial_ports
from .deps import Container
from .security import TOKEN_HEADER

router = APIRouter(prefix="/api", tags=["system"])


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/health", response_model=HealthOut, summary="Liveness check")
def health() -> dict:
    return {"status": "ok", "app": APP_NAME, "version": APP_VERSION, "time": time.time()}


@router.get("/session", response_model=SessionOut, summary="Session token for this browser", description="Readable only from allowed origins. Required on every state-changing REST call and on the WebSocket. In the online demo, sending a live token resumes that visitor's sandbox; otherwise a new sandbox is created.")
async def session(request: Request) -> dict:
    registry = getattr(request.app.state, "sandboxes", None)
    if registry is None:
        config = request.app.state.container.config
        return {"token": config.session_token, "header": TOKEN_HEADER, "websocket_path": "/ws", "bind_host": config.host, "hosted": False, "limits": None}
    sandbox = await registry.resume_or_create(request.headers.get(TOKEN_HEADER), client_ip(request))
    return {"token": sandbox.token, "header": TOKEN_HEADER, "websocket_path": "/ws", "bind_host": registry.config.host, "hosted": True, "limits": registry.limits.public()}


@router.get("/status", response_model=StatusOut, summary="Current modes and system status")
def status(c: Container) -> dict:
    return c.status()


@router.get("/snapshot", summary="Full state snapshot (same as the WebSocket hello message)")
def snapshot(c: Container) -> dict:
    return c.snapshot()


@router.get("/activity", response_model=list[ActivityEntry], summary="Recent activity log entries")
def activity(c: Container, limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    return c.activity.recent(limit)


@router.get("/ports", response_model=list[PortOut], summary="Discover Windows COM ports", description="Lists serial ports via PySerial. A port shown here may still be busy in another program (Arduino Serial Monitor or a CLI script). Always empty in the online demo.")
def ports(c: Container) -> list[dict]:
    if c.config.hosted:
        return []
    owned = c.sensors.owned_ports()
    out = []
    for port in list_serial_ports():
        port["owned_by"] = owned.get(port["device"])
        out.append(port)
    return out
