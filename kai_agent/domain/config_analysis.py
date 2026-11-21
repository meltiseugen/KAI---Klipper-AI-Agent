"""Public results of read-only configuration analysis."""

from pydantic import Field

from kai_agent.domain.base import BaseModel
from kai_agent.domain.evidence import IssueFinding, SourceCitation


class ConfigAnalysis(BaseModel):
    revision: str
    root_file: str | None
    complete: bool
    files_checked: int
    findings: list[IssueFinding] = Field(default_factory=list)
    citations: list[SourceCitation] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
