"""Session-protected application knowledge; no printer writes or model downloads."""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from typing import Callable, Iterator

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field

from klipperai_agent.application.chat import ChatService
from klipperai_agent.application.knowledge import PrinterKnowledge
from klipperai_agent.domain.base import BaseModel
from klipperai_agent.domain.knowledge import KnowledgeConflict, KnowledgeSetup


class KnowledgeRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)

    class Config:
        extra = "forbid"


class SaveKnowledgeRequest(KnowledgeRequest):
    setup: KnowledgeSetup


class ReviewMappingsRequest(KnowledgeRequest):
    role: str = Field(regex=r"^[a-z][a-z0-9_-]{0,39}$")
    signature: str = Field(regex=r"^[a-f0-9]{64}$")
    revision: int = Field(ge=0)


@contextmanager
def storage_errors() -> Iterator[None]:
    try:
        yield
    except KnowledgeConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise HTTPException(503, "Printer knowledge storage is unavailable.") from exc


def knowledge_routes(get_service: Callable[[Request], ChatService]) -> APIRouter:
    router = APIRouter(prefix="/api/knowledge")

    def knowledge(request: Request, session_id: str) -> PrinterKnowledge:
        service = get_service(request)
        if service.sessions.get(session_id) is None:
            raise HTTPException(403, "Invalid or expired session.")
        if service.knowledge is None:
            raise HTTPException(404, "Printer knowledge is unavailable.")
        return service.knowledge

    @router.get("")
    async def status(request: Request, session_id: str, response: Response) -> dict:
        response.headers["Cache-Control"] = "no-store"
        with storage_errors():
            return await knowledge(request, session_id).status()

    @router.put("/details")
    async def save(payload: SaveKnowledgeRequest, request: Request) -> KnowledgeSetup:
        with storage_errors():
            return await knowledge(request, payload.session_id).save(payload.setup)

    @router.post("/refresh", status_code=202)
    async def refresh(payload: KnowledgeRequest, request: Request) -> dict:
        with storage_errors():
            return await knowledge(request, payload.session_id).start_refresh()

    @router.get("/documents/{document_id}")
    async def download(document_id: str, request: Request, session_id: str) -> Response:
        service = knowledge(request, session_id)
        if not re.fullmatch(r"[a-f0-9]{32}", document_id):
            raise HTTPException(404, "Document not found.")
        with storage_errors():
            result = await service.original(document_id)
        if result is None:
            raise HTTPException(404, "Document has not been cached.")
        doc, original = result
        extension = {"pdf": "pdf", "image": "png", "jpeg": "jpg", "html": "html", "text": "txt"}[
            doc.kind
        ]
        return Response(
            original,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{document_id}.{extension}"',
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )

    @router.post("/review-mappings")
    async def review(payload: ReviewMappingsRequest, request: Request) -> KnowledgeSetup:
        with storage_errors():
            return await knowledge(request, payload.session_id).review_mappings(
                payload.role, payload.signature, payload.revision
            )

    return router
