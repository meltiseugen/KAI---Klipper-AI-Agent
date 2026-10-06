from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, validator

from klipperai_agent.contracts.base import BaseModel
from klipperai_agent.domain.evidence import (
    AgentEvent as AgentEvent,
)
from klipperai_agent.domain.evidence import (
    ArtifactInput as ArtifactInput,
)
from klipperai_agent.domain.evidence import (
    ArtifactKind as ArtifactKind,
)
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
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=40000)
    artifacts: list[ArtifactInput] = Field(default_factory=list)
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_items=100)

    @validator("message")
    def _reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Enter a question first.")
        return value


class ChatResponse(BaseModel):
    session_id: str
    thread_id: str
    response: str
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


class BootstrapResponse(BaseModel):
    session_id: str
    provider: str
    provider_model: str | None = None
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
