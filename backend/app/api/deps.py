from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from ..container import AppContainer
from .security import TOKEN_HEADER


def get_container(request: Request) -> AppContainer:
    registry = getattr(request.app.state, "sandboxes", None)
    if registry is not None:
        return registry.require(request.headers.get(TOKEN_HEADER))
    return request.app.state.container


Container = Annotated[AppContainer, Depends(get_container)]
