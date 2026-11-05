from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from ..container import AppContainer


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


Container = Annotated[AppContainer, Depends(get_container)]
