"""Provider administration stays behind the existing trusted UI/session boundary."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Callable, Iterator

from fastapi import APIRouter, HTTPException, Request

from klipperai_agent.bootstrap.container import AppContainer
from klipperai_agent.domain.provider_settings import (
    ProviderConflict,
    ProviderLimitError,
    ProviderUpdate,
)


@contextmanager
def provider_errors() -> Iterator[None]:
    try:
        yield
    except ProviderConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except ProviderLimitError as exc:
        raise HTTPException(429, str(exc)) from None
    except (OSError, sqlite3.Error):
        raise HTTPException(503, "Private provider storage is unavailable.") from None
    except ValueError:
        raise HTTPException(
            400,
            "Provider validation failed. Check the key, model access and configuration; existing settings were kept.",
        ) from None


def provider_routes(get_container: Callable[[Request], AppContainer]) -> APIRouter:
    router = APIRouter(prefix="/api/providers")

    def manager(request: Request, session_id: str):
        container = get_container(request)
        if container.sessions.get(session_id) is None:
            raise HTTPException(403, "Invalid or expired session.")
        if container.providers is None:
            raise HTTPException(404, "Provider management is unavailable.")
        return container.providers

    @router.get("")
    async def status(request: Request, session_id: str) -> dict:
        with provider_errors():
            return manager(request, session_id).status()

    @router.post("/validate")
    async def validate(request: Request, payload: ProviderUpdate) -> dict:
        with provider_errors():
            return await manager(request, payload.session_id).update(payload, save=False)

    @router.put("")
    async def save(request: Request, payload: ProviderUpdate) -> dict:
        with provider_errors():
            return await manager(request, payload.session_id).update(payload, save=True)

    return router
