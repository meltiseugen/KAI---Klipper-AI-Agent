"""Session-protected live status; streams coalesce updates and retain no history."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from klipperai_agent.bootstrap.container import AppContainer
from klipperai_agent.domain.moonraker import MoonrakerObservation


async def status_events(
    state: MoonrakerObservation, valid: Callable[[], bool], *, interval: float = 1
) -> AsyncIterator[str]:
    revision = -1
    while valid():
        if state.revision != revision:
            revision = state.revision
            yield "event: status\ndata: " + json.dumps(state.snapshot(), allow_nan=False) + "\n\n"
        else:
            yield ": heartbeat\n\n"
        await asyncio.sleep(interval)
    yield "event: expired\ndata: {}\n\n"


def moonraker_routes(get_container: Callable[[Request], AppContainer]) -> APIRouter:
    router = APIRouter(prefix="/api/moonraker")

    def connection(request: Request, session_id: str):
        container = get_container(request)
        if container.sessions.get(session_id) is None:
            raise HTTPException(403, "Invalid or expired session.")
        if container.moonraker_agent is None:
            raise HTTPException(404, "Moonraker agent integration is disabled.")
        return container.moonraker_agent.state, container.sessions

    @router.get("")
    async def status(request: Request, session_id: str) -> dict:
        state, _ = connection(request, session_id)
        return state.snapshot()

    @router.get("/events")
    async def events(request: Request, session_id: str) -> StreamingResponse:
        state, sessions = connection(request, session_id)
        return StreamingResponse(
            status_events(state, lambda: sessions.get(session_id) is not None),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return router
