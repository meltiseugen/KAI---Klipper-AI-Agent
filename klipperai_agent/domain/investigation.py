"""Durable investigations contain public evidence and outcomes, never model reasoning."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import Field, validator

from klipperai_agent.domain.base import BaseModel
from klipperai_agent.domain.evidence import AgentEvent, ArtifactInput, IssueFinding, SourceCitation
from klipperai_agent.domain.messages import ChatHistoryMessage
from klipperai_agent.domain.proposals import ConfigProposal, PatchProposal


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Evidence(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    observed_at: str = Field(default_factory=utc_now)
    source: str
    content: str = Field(max_length=16000)
    config_revision: str | None = None
    citations: list[SourceCitation] = Field(default_factory=list)

    def historical_context(self) -> dict[str, object]:
        return {
            "evidence_id": self.id,
            "observed_at": self.observed_at,
            "source": self.source,
            "content": self.content,
            "config_revision": self.config_revision,
            "freshness": "historical; recheck live state and config before relying on it",
        }


class InvestigationRequest(BaseModel):
    user_message: str
    conversation_context: str = ""
    artifacts: list[ArtifactInput] = Field(default_factory=list)
    memory: list[Evidence] = Field(default_factory=list)


class MemorySource(BaseModel):
    evidence_id: str
    source: str
    observed_at: str


class InvestigationResult(BaseModel):
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


class Investigation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    printer_id: str
    title: str
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    revision: int = 0
    turns: list[InvestigationTurn] = Field(default_factory=list)

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
