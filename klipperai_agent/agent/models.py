"""Contracts shared by agent orchestration and provider adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from pydantic import Field, validator

from klipperai_agent.domain.base import BaseModel
from klipperai_agent.domain.evidence import AgentEvent, SourceCitation
from klipperai_agent.domain.proposals import ConfigProposal

EventSink = Callable[[AgentEvent], Awaitable[None]]


class AgentAnswer(BaseModel):
    response: str = Field(min_length=1, max_length=24000)
    next_actions: list[str] = Field(default_factory=list, max_items=8)
    config_proposals: list[ConfigProposal] = Field(default_factory=list, max_items=5)

    @validator("response", pre=True)
    def _strip_response(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str


@dataclass
class ModelTurn:
    # Preserve provider output (including encrypted reasoning) for the next turn.
    output: list[dict[str, Any]]
    calls: list[ToolCall] = field(default_factory=list)
    text: str = ""


class AgentModel(Protocol):
    async def respond(
        self,
        conversation: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelTurn: ...


@dataclass
class SearchResult:
    summary: str
    citations: list[SourceCitation] = field(default_factory=list)


class WebSearch(Protocol):
    async def search(self, query: str) -> SearchResult: ...


@dataclass(frozen=True)
class AgentLimits:
    max_steps: int = 8
    max_tool_calls: int = 12
    tool_timeout_seconds: float = 30.0
    run_timeout_seconds: float = 180.0
    max_context_chars: int = 120000
    max_result_chars: int = 16000
