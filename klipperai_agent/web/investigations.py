"""Read, forget, and recheck KlipperAI records. No printer mutation endpoints."""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, HTTPException, Request, Response

from klipperai_agent.application.chat import ChatService
from klipperai_agent.application.investigations import InvestigationMemory
from klipperai_agent.domain.investigation import (
    Investigation,
    InvestigationResult,
    InvestigationTurn,
)
from klipperai_agent.domain.repositories import InvestigationConflict


def investigation_routes(get_service: Callable[[Request], ChatService]) -> APIRouter:
    router = APIRouter(prefix="/api/investigations")

    def memory(request: Request, session_id: str) -> InvestigationMemory:
        service = get_service(request)
        if service.sessions.get(session_id) is None:
            raise HTTPException(403, "Invalid or expired session.")
        if service.investigations is None:
            raise HTTPException(404, "Investigation storage is unavailable.")
        return service.investigations

    @router.get("")
    async def recent(request: Request, session_id: str) -> list[dict]:
        records = await memory(request, session_id).recent()
        return [item.model_dump(exclude={"turns"}) for item in records]

    @router.get("/{investigation_id}")
    async def get(investigation_id: str, request: Request, session_id: str) -> Investigation:
        record = await memory(request, session_id).get(investigation_id)
        if record is None:
            raise HTTPException(404, "Investigation not found.")
        return record

    @router.delete("/{investigation_id}", status_code=204)
    async def forget(investigation_id: str, request: Request, session_id: str) -> Response:
        await memory(request, session_id).delete(investigation_id)
        return Response(status_code=204)

    @router.post("/{investigation_id}/proposals/{proposal_id}/revalidate")
    async def revalidate(
        investigation_id: str, proposal_id: str, request: Request, session_id: str
    ) -> InvestigationTurn:
        records = memory(request, session_id)
        record = await get(investigation_id, request, session_id)
        reviewer = get_service(request).proposal_review
        proposal = next(
            (
                proposal
                for turn in reversed(record.turns)
                for proposal in turn.result.config_proposals
                if proposal.review and proposal.review.proposal_id == proposal_id
            ),
            None,
        )
        if proposal is None or reviewer is None:
            raise HTTPException(404, "Reviewed proposal not found.")
        result = InvestigationResult(
            response_text="Rechecked the proposal against current configuration. All edits remain manual.",
            config_proposals=[proposal],
        )
        await reviewer.review(result, revalidate=True)
        try:
            return await records.remember(record, f"Recheck proposal: {proposal.title}", result, [])
        except InvestigationConflict as exc:
            raise HTTPException(409, str(exc)) from exc

    return router
