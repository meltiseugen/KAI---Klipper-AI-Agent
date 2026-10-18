"""Only explicit UI confirmation can create durable printer statements."""

from __future__ import annotations

from typing import Callable, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field, StrictBool, validator

from klipperai_agent.application.chat import ChatService
from klipperai_agent.application.investigations import InvestigationMemory
from klipperai_agent.domain.base import BaseModel
from klipperai_agent.domain.investigation import ConfirmedMemory
from klipperai_agent.domain.redaction import redact_text
from klipperai_agent.domain.repositories import InvestigationConflict


class MemoryConfirmation(BaseModel):
    session_id: str
    kind: Literal["fact", "preference", "resolution"]
    content: str = Field(min_length=1, max_length=2000)
    confirmed: StrictBool
    investigation_id: str | None = Field(default=None, min_length=1, max_length=128)
    evidence_ids: list[str] = Field(default_factory=list, max_items=6)

    @validator("content")
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Enter the statement you are confirming.")
        return redact_text(value.strip())

    @validator("confirmed")
    def explicit_confirmation(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Explicit confirmation is required.")
        return value

    class Config:
        extra = "forbid"


def memory_routes(get_service: Callable[[Request], ChatService]) -> APIRouter:
    router = APIRouter(prefix="/api/memory")

    def memory(request: Request, session_id: str) -> InvestigationMemory:
        service = get_service(request)
        if service.sessions.get(session_id) is None:
            raise HTTPException(403, "Invalid or expired session.")
        if service.investigations is None:
            raise HTTPException(404, "Investigation storage is unavailable.")
        return service.investigations

    @router.get("")
    async def list_entries(request: Request, session_id: str) -> list[ConfirmedMemory]:
        return await memory(request, session_id).confirmed()

    @router.post("", status_code=201)
    async def confirm(request: Request, payload: MemoryConfirmation) -> ConfirmedMemory:
        records = memory(request, payload.session_id)
        try:
            return await records.confirm(
                ConfirmedMemory(
                    kind=payload.kind,
                    content=payload.content,
                    investigation_id=payload.investigation_id,
                ),
                payload.evidence_ids,
            )
        except InvestigationConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.delete("/{memory_id}", status_code=204)
    async def forget(memory_id: str, request: Request, session_id: str) -> Response:
        await memory(request, session_id).forget_confirmed(memory_id)
        return Response(status_code=204)

    return router
