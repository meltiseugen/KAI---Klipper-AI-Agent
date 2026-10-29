"""Durable investigations contain public evidence and outcomes, never model reasoning."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import Field, validator

from klipperai_agent.domain.artifacts import CollectedArtifact
from klipperai_agent.domain.base import BaseModel
from klipperai_agent.domain.context import AgentMode, ContextItem
from klipperai_agent.domain.evidence import (
    AgentEvent,
    ArtifactInput,
    GroundedClaim,
    IssueFinding,
    SourceCitation,
)
from klipperai_agent.domain.messages import ChatHistoryMessage
from klipperai_agent.domain.model_usage import ModelUsage
from klipperai_agent.domain.proposals import ConfigProposal, PatchProposal


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Evidence(CollectedArtifact):
    def historical_context(self) -> dict[str, object]:
        return {
            "evidence_id": self.id,
            "observed_at": self.observed_at,
            "source": self.source,
            "content": self.content,
            "config_revision": self.config_revision,
            "freshness": "historical; recheck live state and config before relying on it",
            "artifact": {
                **self.prompt_metadata(),
                "freshness": "historical",
                "origin": "memory",
                "content_format": "text",
                "status": "partial"
                if self.original_characters > len(self.content)
                else self.status,
            },
        }


class InvestigationRequest(BaseModel):
    user_message: str
    mode: AgentMode = "chat"
    conversation_context: str = ""
    artifacts: list[ArtifactInput] = Field(default_factory=list)
    memory: list[Evidence] = Field(default_factory=list)


class MemorySource(BaseModel):
    evidence_id: str
    source: str
    observed_at: str


class InvestigationResult(BaseModel):
    model_usage: ModelUsage = Field(default_factory=ModelUsage)
    mode: AgentMode = "chat"
    workflow: Literal["general", "diagnosis", "config_explanation", "config_draft"] = "general"
    answer_claims: list[GroundedClaim] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    context_included: list[ContextItem] = Field(default_factory=list)
    response_text: str = Field(default="No response generated.", min_length=1)
    next_actions: list[str] = Field(default_factory=list)
    findings: list[IssueFinding] = Field(default_factory=list)
    config_proposals: list[ConfigProposal] = Field(default_factory=list)
    patch_proposals: list[PatchProposal] = Field(default_factory=list)
    source_citations: list[SourceCitation] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    moonraker_reachable: bool | None = None
    agent_events: list[AgentEvent] = Field(default_factory=list)
    agent_status: Literal["completed", "limited", "error"] = "completed"
    memory_sources: list[MemorySource] = Field(default_factory=list)

    @validator("response_text", pre=True)
    def _strip_response(cls, value: str) -> str:
        return value.strip()


class InvestigationTurn(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=utc_now)
    question: str
    result: InvestigationResult
    imported_history: list[ChatHistoryMessage] = Field(default_factory=list)


class PendingInvestigation(BaseModel):
    """Replayable public input and observations, without provider conversation state."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=utc_now)
    mode: AgentMode = "chat"
    message: str
    artifacts: list[ArtifactInput] = Field(default_factory=list)
    history: list[ChatHistoryMessage] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    attempts: int = 0


class ConfirmedMemory(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    kind: Literal["fact", "preference", "resolution"]
    content: str = Field(min_length=1, max_length=2000)
    confirmed_at: str = Field(default_factory=utc_now)
    investigation_id: str | None = None
    evidence: list[Evidence] = Field(default_factory=list, max_items=6)

    def as_evidence(self) -> Evidence:
        return Evidence(
            id=self.id,
            source=f"user-confirmed:{self.kind}",
            observed_at=self.confirmed_at,
            content=(
                f"User-confirmed {self.kind}: {self.content}\n"
                "This is a dated user statement, not independent verification or live state."
            ),
        )


class Investigation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    printer_id: str
    title: str
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    revision: int = 0
    turns: list[InvestigationTurn] = Field(default_factory=list)
    pending: PendingInvestigation | None = None

    def history(self) -> list[ChatHistoryMessage]:
        messages = []
        for turn in self.turns:
            messages.extend(turn.imported_history)
            messages.extend(
                [
                    ChatHistoryMessage(role="user", text=turn.question[:8000]),
                    ChatHistoryMessage(role="assistant", text=turn.result.response_text[:8000]),
                ]
            )
        return messages
