from __future__ import annotations

import hmac
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .errors import error_body

TOKEN_HEADER = "x-session-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
TOKEN_EXEMPT_PATHS = {"/api/session", "/api/health"}


def tokens_match(expected: str, supplied: str | None) -> bool:
    if not supplied:
        return False
    return hmac.compare_digest(expected.encode(), supplied.encode())


def origin_matches_host(origin: str, host: str | None) -> bool:
    if not host:
        return False
    try:
        netloc = urlsplit(origin).netloc
    except ValueError:
        return False
    return bool(netloc) and netloc.lower() == host.lower()


class AccessGuardMiddleware:
    def __init__(self, app: ASGIApp, allowed_origins: list[str], token: str | None, same_origin: bool = False):
        self.app = app
        self.allowed_origins = set(allowed_origins)
        self.token = token
        self.same_origin = same_origin

    def origin_allowed(self, origin: str, host: str | None) -> bool:
        if self.same_origin:
            return origin_matches_host(origin, host)
        return origin in self.allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        method = scope.get("method", "GET").upper()
        path = scope.get("path", "")
        origin = headers.get("origin")
        if origin is not None and not self.origin_allowed(origin, headers.get("host")):
            response = JSONResponse(status_code=403, content=error_body("origin_rejected", f"Origin '{origin}' is not allowed"))
            await response(scope, receive, send)
            return
        if path.startswith("/api/") and headers.get("sec-fetch-site") == "cross-site":
            response = JSONResponse(status_code=403, content=error_body("cross_site_rejected", "Cross-site requests are not allowed"))
            await response(scope, receive, send)
            return
        if self.token is not None and path.startswith("/api/") and method not in SAFE_METHODS and path not in TOKEN_EXEMPT_PATHS:
            if not tokens_match(self.token, headers.get(TOKEN_HEADER)):
                response = JSONResponse(status_code=401, content=error_body("invalid_session_token", "Missing or invalid X-Session-Token header"))
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def websocket_allowed(origin: str | None, token: str | None, allowed_origins: list[str], expected_token: str) -> tuple[bool, str]:
    if origin is not None and origin not in allowed_origins:
        return False, "origin_rejected"
    if not tokens_match(expected_token, token):
        return False, "invalid_session_token"
    return True, "ok"
