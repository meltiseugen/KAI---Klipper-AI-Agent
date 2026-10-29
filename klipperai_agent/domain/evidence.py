from __future__ import annotations

from typing import Literal

from pydantic import Field, root_validator

from klipperai_agent.domain.base import BaseModel
from klipperai_agent.domain.recovery import RecoveryPlaybook

ArtifactKind = Literal[
    "klippy_log",
    "moonraker_log",
    "system_log",
    "config_snippet",
    "notes",
]


Severity = Literal["low", "medium", "high", "critical"]


def severity_rank(severity: str) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(severity, 0)


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
    severity_rank: int = 0
    confidence: Literal["high", "medium", "low", "unknown"] = "unknown"
    confidence_scope: Literal["observation", "hypothesis", "unassessed"] = "unassessed"
    confidence_reason: str = (
        "Confidence has not been assessed. Severity describes impact, not certainty."
    )
    evidence_ids: list[str] = Field(default_factory=list)
    citations: list[SourceCitation] = Field(default_factory=list)
    recovery: RecoveryPlaybook | None = None

    @root_validator
    def _derive_rank(cls, values: dict) -> dict:
        values["severity_rank"] = severity_rank(values.get("severity", ""))
        return values


class SourceCitation(BaseModel):
    label: str
    path: str
    line_number: int | None = None
    section: str | None = None
    excerpt: str = ""
    url: str | None = None
    end_line: int | None = Field(default=None, ge=1)
    line_basis: Literal["excerpt", "file", "none"] = "none"
    evidence_id: str | None = None
    observed_at: str | None = None
    config_revision: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    source_digest: str | None = None
    firmware_commit: str | None = None


IssueFinding.update_forward_refs(SourceCitation=SourceCitation)


class GroundedClaim(BaseModel):
    claim: str
    citations: list[SourceCitation]


class AgentEvent(BaseModel):
    kind: Literal[
        "tool_started",
        "tool_completed",
        "tool_error",
        "model_started",
        "model_completed",
        "limit",
        "error",
    ]
    message: str
    tool: str | None = None
