from __future__ import annotations

from fastapi import APIRouter

from ..control.actions import allowlist_description
from ..schemas.control import ArmRequest, DisarmRequest, EmergencyStopRequest
from .deps import Container

router = APIRouter(prefix="/api/control", tags=["control"])


@router.get("", summary="PC-control state: armed, Emergency Stop latch, counters, recent outcomes")
def state(c: Container) -> dict:
    return c.control.state()


@router.get("/allowlist", summary="Action types and keys that may ever reach the OS")
def allowlist() -> dict:
    return allowlist_description()


@router.post("/arm", summary="Explicitly arm PC control", description="Fails with 409 and a list of reasons unless PC control is enabled in Settings, Emergency Stop is reset, recognition runs with a trusted compatible model, the sensor streams, mappings are enabled and the control session is live.")
def arm(body: ArmRequest, c: Container) -> dict:
    return c.control.arm(body.control_session_id, body.confirm)


@router.post("/disarm", summary="Disarm PC control")
def disarm(body: DisarmRequest, c: Container) -> dict:
    return c.control.disarm(body.reason or "user")


@router.post("/emergency-stop", summary="Emergency Stop: disarm immediately, clear pending actions, latch until reset")
def emergency_stop(body: EmergencyStopRequest, c: Container) -> dict:
    return c.control.emergency_stop(body.source or "api")


@router.post("/reset", summary="Reset the Emergency Stop latch (does not re-arm)")
def reset(c: Container) -> dict:
    return c.control.reset_estop()
