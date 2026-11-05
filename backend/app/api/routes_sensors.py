from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from sqlalchemy import select

from ..database.models import SensorRow
from ..hosting.sandboxes import INACTIVE_SENSOR_STATUSES, active_sensors
from ..schemas.sensors import ConnectRequest, DemoAutoRequest, DemoPerformRequest, SensorOut, SensorPatch
from .deps import Container
from .errors import AppError, conflict

router = APIRouter(prefix="/api/sensors", tags=["sensors"])
demo_router = APIRouter(prefix="/api/demo", tags=["demo"])


def remember_sensor(c: Container, sensor_id: str, hand: str, port: str, baud: int, workspace: str) -> None:
    with c.db.begin() as db:
        row = db.get(SensorRow, sensor_id)
        if row is None:
            db.add(SensorRow(sensor_id=sensor_id, workspace=workspace, hand=hand, last_port=port, baud=baud))
        else:
            row.hand = hand
            row.last_port = port
            row.baud = baud
            row.workspace = workspace


def check_online_sensor_limit(c: Container, request: Request) -> None:
    if not c.config.hosted:
        return
    limit = c.config.hosted_limits.max_sensors
    if active_sensors(c) >= limit:
        raise conflict("sensor_limit_online", f"The online demo runs at most {limit} simulated sensors at a time. Disconnect one first.")
    registry = getattr(request.app.state, "sandboxes", None)
    if registry is not None:
        registry.check_sensor_capacity()


@router.get("", response_model=list[SensorOut], summary="Connected and recently connected sensors")
def list_sensors(c: Container) -> list[dict]:
    return c.sensors.snapshot()


@router.get("/known", summary="Sensor identities remembered from previous connections")
def known_sensors(c: Container) -> list[dict]:
    workspace = c.workspace()
    with c.db() as db:
        rows = db.scalars(select(SensorRow).where(SensorRow.workspace == workspace).order_by(SensorRow.sensor_id)).all()
        return [{"sensor_id": r.sensor_id, "hand": r.hand, "last_port": r.last_port, "baud": r.baud} for r in rows]


@router.post("", response_model=SensorOut, status_code=201, summary="Connect a sensor", description="Opens the COM port (or a simulated source in Demo Mode) and starts streaming. One owner per port.")
def connect(body: ConnectRequest, c: Container, request: Request) -> dict:
    if c.config.hosted and body.demo_rate_hz > c.config.hosted_limits.max_demo_rate_hz:
        raise AppError("rate_limit_online", f"The online demo simulates at most {c.config.hosted_limits.max_demo_rate_hz:g} Hz", 422)
    check_online_sensor_limit(c, request)
    baud = body.baud or c.settings.current.acquisition.default_baud
    demo_options = {"rate_hz": body.demo_rate_hz, "auto": body.demo_auto} if body.simulated else None
    session = c.sensors.connect(body.port, baud, body.sensor_id, body.hand, simulated=body.simulated, demo_options=demo_options)
    remember_sensor(c, session.sensor_id, session.hand, session.port, session.baud, session.workspace)
    if c.settings.current.selected_sensor_id is None:
        c.settings.update({"selected_sensor_id": session.sensor_id})
    return c.sensors.describe(session)


@router.get("/{sensor_id}", response_model=SensorOut, summary="Sensor health, counters and clock information")
def get_sensor(sensor_id: str, c: Container) -> dict:
    return c.sensors.describe(c.sensors.get(sensor_id))


@router.patch("/{sensor_id}", response_model=SensorOut, summary="Change a sensor's ID (disconnected only) or Left/Right label")
def patch_sensor(sensor_id: str, body: SensorPatch, c: Container) -> dict:
    session = c.sensors.update(sensor_id, body.sensor_id, body.hand)
    remember_sensor(c, session.sensor_id, session.hand, session.port, session.baud, session.workspace)
    if body.sensor_id and c.settings.current.selected_sensor_id == sensor_id:
        c.settings.update({"selected_sensor_id": session.sensor_id})
    return c.sensors.describe(session)


@router.post("/{sensor_id}/disconnect", response_model=SensorOut, summary="Disconnect and release the port")
def disconnect(sensor_id: str, c: Container) -> dict:
    return c.sensors.describe(c.sensors.disconnect(sensor_id))


@router.post("/{sensor_id}/reconnect", response_model=SensorOut, summary="Reconnect using the same port and settings")
def reconnect(sensor_id: str, c: Container, request: Request) -> dict:
    if c.config.hosted and c.sensors.get(sensor_id).status in INACTIVE_SENSOR_STATUSES:
        check_online_sensor_limit(c, request)
    return c.sensors.describe(c.sensors.reconnect(sensor_id))


@router.delete("/{sensor_id}", status_code=204, summary="Disconnect and remove from the live list (remembered identity is kept)")
def remove(sensor_id: str, c: Container) -> Response:
    c.sensors.remove(sensor_id)
    if c.settings.current.selected_sensor_id == sensor_id:
        c.settings.update({"selected_sensor_id": None})
    return Response(status_code=204)


@router.get("/{sensor_id}/buffer", summary="Export the live buffer (valid samples only)", description="Returns the most recent samples held in memory for display, in source units (g, deg/s).")
def export_buffer(sensor_id: str, c: Container, seconds: float = Query(10.0, gt=0, le=60), fmt: str = Query("json", pattern="^(json|csv)$")):
    session = c.sensors.get(sensor_id)
    t, h, v = session.buffer.window(seconds)
    if fmt == "csv":
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(["t_us", "ax", "ay", "az", "gx", "gy", "gz", "host_rx_ns"])
        for i in range(len(t)):
            writer.writerow([int(t[i]), *[f"{x:.6g}" for x in v[i]], int(h[i])])
        name = f"{sensor_id}_live_{int(seconds)}s.csv"
        return Response(out.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})
    return {
        "sensor_id": sensor_id,
        "simulated": session.simulated,
        "epoch": session.buffer.epoch,
        "t_us": t.tolist(),
        "values": v.tolist(),
        "units": {"accel": "g", "gyro": "deg/s", "time": "us (device, unwrapped)"},
    }


def demo_session(c: Container, sensor_id: str):
    session = c.sensors.get(sensor_id)
    if not session.simulated or session.demo is None:
        raise conflict("not_simulated", "Only simulated (DEMO-*) sensors accept demo commands")
    return session


@demo_router.post("/sensors/{sensor_id}/perform", summary="Make a simulated sensor perform a synthetic gesture")
def demo_perform(sensor_id: str, body: DemoPerformRequest, c: Container) -> dict:
    session = demo_session(c, sensor_id)
    if not session.demo.perform(body.label):
        raise AppError("unsupported_demo_gesture", f"The simulator can produce: {', '.join(session.demo.gestures)}", 422)
    return {"sensor_id": sensor_id, "queued": body.label, "simulated": True}


@demo_router.post("/sensors/{sensor_id}/auto", summary="Toggle random synthetic gestures on a simulated sensor")
def demo_auto(sensor_id: str, body: DemoAutoRequest, c: Container) -> dict:
    session = demo_session(c, sensor_id)
    session.demo.set_auto(body.enabled)
    c.sensors.publish_connections()
    return {"sensor_id": sensor_id, "auto": body.enabled, "simulated": True}


@demo_router.get("/sensors/{sensor_id}/history", summary="Ground truth of gestures the simulator performed")
def demo_history(sensor_id: str, c: Container) -> list[dict]:
    session = demo_session(c, sensor_id)
    return list(session.demo.history)
