"""Public records of provider attempts; old investigations have unknown usage."""

from typing import Literal

from pydantic import Field

from klipperai_agent.domain.base import BaseModel


class ModelUsage(BaseModel):
    status: Literal["unknown", "not_used", "attempted", "completed"] = "unknown"
    requests_started: int = Field(default=0, ge=0)
    requests_completed: int = Field(default=0, ge=0)
    models: list[str] = Field(default_factory=list)
