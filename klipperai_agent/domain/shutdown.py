"""Public observations for a shutdown investigation, independent of I/O adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from klipperai_agent.domain.base import BaseModel
from klipperai_agent.domain.evidence import SourceCitation


@dataclass
class LogExcerpt:
    source: str
    content: str
    partial: bool = False


@dataclass
class ShutdownLogs:
    excerpts: list[LogExcerpt] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class HostObservation:
    current: dict[str, Any] = field(default_factory=dict)
    kernel: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class ShutdownIncident(BaseModel):
    family: str
    message: str
    mcu: str | None = None
    source: str
    excerpt_line: int
    monotonic_time: float | None = None
    estimated_unix_time: float | None = None
    statistics: dict[str, Any]
    nearby_errors: list[str]
    citations: list[SourceCitation]


class CauseAssessment(BaseModel):
    cause: str
    confidence: str
    evidence: list[str]
    next_steps: list[str]
