from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import Field, validator

from klipperai_agent.contracts.base import BaseModel
from klipperai_agent.domain.artifacts import CollectedArtifact
from klipperai_agent.domain.context import AgentMode, ContextItem
from klipperai_agent.domain.evidence import (
    AgentEvent as AgentEvent,
)
from klipperai_agent.domain.evidence import (
    ArtifactInput as ArtifactInput,
)
from klipperai_agent.domain.evidence import (
    ArtifactKind as ArtifactKind,
)
from klipperai_agent.domain.evidence import GroundedClaim
from klipperai_agent.domain.evidence import (
    IssueFinding as IssueFinding,
)
from klipperai_agent.domain.evidence import (
    Severity as Severity,
)
from klipperai_agent.domain.evidence import (
    SourceCitation as SourceCitation,
)
from klipperai_agent.domain.investigation import MemorySource as MemorySource
from klipperai_agent.domain.messages import (
    ChatHistoryMessage as ChatHistoryMessage,
)
from klipperai_agent.domain.model_usage import ModelUsage
from klipperai_agent.domain.proposals import (
    ConfigProposal as ConfigProposal,
)
from klipperai_agent.domain.proposals import (
    PatchProposal as PatchProposal,
)
from klipperai_agent.domain.proposals import (
    _stringify_dict as _stringify_dict,
)


class DetectedAddonSummary(BaseModel):
    name: str
    source: str
    confidence: str = "medium"
    detail: str | None = None


class PrinterProfileSummary(BaseModel):
    firmware_flavor: str | None = None
    firmware_version: str | None = None
    host_model: str | None = None
    host_distribution: str | None = None
    mainboard: str | None = None
    mainboard_mcu: str | None = None
    toolhead: str | None = None
    toolhead_board: str | None = None
    probe_type: str | None = None
    accelerometer: str | None = None
    filament_sensor: str | None = None
    camera_stack: str | None = None
    bed_mesh_configured: bool = False
    input_shaper_configured: bool = False
    printer_state: str | None = None
    canbus_enabled: bool = False
    addons: list[DetectedAddonSummary] = Field(default_factory=list)
    summary: str = ""


class ChatRequest(BaseModel):
    session_id: str
    mode: AgentMode = "chat"
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=40000)
    artifacts: list[ArtifactInput] = Field(default_factory=list, max_items=8)
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_items=100)

    @validator("message")
    def _reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Enter a question first.")
        return value

    @validator("artifacts")
    def _bounded_text_artifacts(cls, value: list[ArtifactInput]) -> list[ArtifactInput]:
        if sum(len(item.content) for item in value) > 160000:
            raise ValueError("Attachments exceed 160,000 characters in total.")
        for item in value:
            if not item.content.strip() or re.search(
                r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]", item.content
            ):
                raise ValueError("Attachments must contain non-empty UTF-8 text.")
        return value


class ChatResponse(BaseModel):
    session_id: str
    model_usage: ModelUsage = Field(default_factory=ModelUsage)
    mode: AgentMode = "chat"
    context_included: list[ContextItem] = Field(default_factory=list)
    thread_id: str
    response: str
    workflow: Literal["general", "diagnosis", "config_explanation", "config_draft"] = "general"
    answer_claims: list[GroundedClaim] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    findings: list[IssueFinding]
    next_actions: list[str]
    config_proposals: list[ConfigProposal] = Field(default_factory=list)
    patch_proposals: list[PatchProposal] = Field(default_factory=list)
    source_citations: list[SourceCitation] = Field(default_factory=list)
    provider: str
    moonraker_reachable: bool | None
    agent_events: list[AgentEvent] = Field(default_factory=list)
    agent_status: Literal["completed", "limited", "error"] = "completed"
    memory_sources: list[MemorySource] = Field(default_factory=list)
    evidence_blocks: list[CollectedArtifact] = Field(default_factory=list, max_items=24)
    evidence_blocks_omitted: int = Field(default=0, ge=0)


class BootstrapResponse(BaseModel):
    session_id: str
    agent_modes: list[AgentMode] = Field(default_factory=list)
    provider: str
    provider_model: str | None = None
    provider_configured: bool = True
    conversation_history_pairs: int = 10
    moonraker_reachable: bool
    klipper_reachable: bool
    expires_at: datetime
    features: list[str]
    printer_profile: PrinterProfileSummary | None = None


class UiSessionResponse(BaseModel):
    session_id: str
    embed_path: str
    expires_at: datetime
