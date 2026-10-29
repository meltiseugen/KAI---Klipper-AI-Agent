"""Public manual troubleshooting plans, never executable printer actions."""

from pydantic import Field

from klipperai_agent.domain.base import BaseModel


class RecoveryPlaybook(BaseModel):
    id: str
    title: str
    required_evidence: list[str]
    steps: list[str]
    verification: list[str]
    stop_conditions: list[str]
    source_urls: list[str] = Field(default_factory=list)
    manual_only: bool = True
