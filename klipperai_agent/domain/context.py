"""Public context receipts. These describe evidence, never model reasoning."""

from typing import Literal

from pydantic import Field

from klipperai_agent.domain.base import BaseModel

AgentMode = Literal["chat", "debug"]
ContextStatus = Literal["included", "partial", "unavailable", "omitted"]


class ModeUnavailableError(ValueError):
    """The selected mode is unavailable with the configured workflow."""


class ContextItem(BaseModel):
    source: str
    status: ContextStatus = "included"
    detail: str = ""
    characters: int = Field(default=0, ge=0)
    observed_at: str
    phase: Literal["initial", "tool"] = "initial"
    sent_to_model: bool = False
