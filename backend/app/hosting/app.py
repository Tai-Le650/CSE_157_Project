from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ..api.errors import install_error_handlers
from ..api.security import AccessGuardMiddleware
from ..container import APP_NAME, APP_VERSION
from ..main import include_routers, mount_frontend
from ..settings.config import AppConfig
from ..wiring import SERVICE_ROUTERS
from .sandboxes import SandboxRegistry

HOSTED_DESCRIPTION = (
    "Public online demo of Gesture-to-PC (CSE 157, UC Merced). Demo Mode only: every visitor gets a private, "
    "temporary sandbox with simulated sensors and simulated keyboard/mouse actions."
)


def configure_hosted_logging() -> None:
    root = logging.getLogger("gesture_to_pc")
    if any(getattr(h, "gesture_to_pc_hosted", False) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.gesture_to_pc_hosted = True
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("gesture_to_pc.activity").setLevel(logging.WARNING)


def create_hosted_app(config: AppConfig) -> FastAPI:
    registry = SandboxRegistry(config)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await registry.start()
        try:
            yield
        finally:
            await registry.stop()

    app = FastAPI(title=APP_NAME, version=APP_VERSION, description=HOSTED_DESCRIPTION, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.sandboxes = registry
    install_error_handlers(app)
    app.add_middleware(AccessGuardMiddleware, allowed_origins=[], token=None, same_origin=True)
    include_routers(app, SERVICE_ROUTERS)
    if config.serve_frontend:
        mount_frontend(app, config)
    return app
