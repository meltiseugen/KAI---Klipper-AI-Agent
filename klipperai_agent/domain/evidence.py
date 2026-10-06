from __future__ import annotations

from typing import Literal

from pydantic import Field

from klipperai_agent.domain.base import BaseModel

ArtifactKind = Literal[
    "klippy_log",
    "moonraker_log",
    "system_log",
    "config_snippet",
    "notes",
]


Severity = Literal["low", "medium", "high", "critical"]


class ArtifactInput(BaseModel):
    kind: ArtifactKind = "notes"
    label: str = Field(default="clipboard", min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=40000)

    def prompt_excerpt(self, limit: int = 4000) -> str:
        if len(self.content) <= limit:
            return self.content
        return f"{self.content[:limit]}\n...[truncated]..."


class IssueFinding(BaseModel):
    code: str
    severity: Severity
    source: str
    summary: str
    evidence: str
    proposed_fix: str


class SourceCitation(BaseModel):
    label: str
    path: str
    line_number: int | None = None
    section: str | None = None
    excerpt: str = ""
    url: str | None = None


class AgentEvent(BaseModel):
    kind: Literal["tool_started", "tool_completed", "tool_error", "limit", "error"]
    message: str
    tool: str | None = None
