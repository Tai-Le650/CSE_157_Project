from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .api import routes_control, routes_sensors, routes_settings, routes_system, routes_ws
from .api.errors import error_body, install_error_handlers
from .api.security import AccessGuardMiddleware
from .container import APP_NAME, APP_VERSION, AppContainer
from .settings.config import AppConfig
from .settings.paths import AppPaths

API_DESCRIPTION = (
    "Local-only API for Gesture-to-PC (CSE 157, UC Merced). Bound to 127.0.0.1. "
    "State-changing requests need the X-Session-Token header from GET /api/session. "
    "Live data, predictions, training progress and status stream over the /ws WebSocket."
)


def create_app(config: AppConfig | None = None) -> FastAPI:
    config = config or AppConfig(paths=AppPaths.default())
    container = AppContainer(config)
    from .wiring import attach_services

    routers = attach_services(container)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await container.startup()
        try:
            yield
        finally:
            await container.shutdown()

    app = FastAPI(title=APP_NAME, version=APP_VERSION, description=API_DESCRIPTION, lifespan=lifespan, redoc_url=None)
    app.state.container = container
    install_error_handlers(app)
    app.add_middleware(AccessGuardMiddleware, allowed_origins=config.allowed_origins, token=config.session_token)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["content-type", "x-session-token"],
        allow_credentials=False,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.allowed_hosts)
    for router in (routes_system.router, routes_settings.router, routes_sensors.router, routes_sensors.demo_router, routes_control.router, *routers, routes_ws.router):
        app.include_router(router)
    if config.serve_frontend:
        mount_frontend(app, config)
    return app


def mount_frontend(app: FastAPI, config: AppConfig) -> None:
    dist = config.paths.frontend_dist.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/") or full_path == "api":
            return JSONResponse(status_code=404, content=error_body("not_found", f"No API route /{full_path}"))
        index = dist / "index.html"
        if not index.is_file():
            return JSONResponse(status_code=503, content=error_body("frontend_not_built", "Build the frontend first: cd frontend; npm install; npm run build. During development use http://127.0.0.1:5173."))
        if full_path:
            candidate = (dist / full_path).resolve()
            if dist in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
