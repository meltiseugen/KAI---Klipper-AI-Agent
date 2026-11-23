"""Public memory proposals and committed changes; never hidden model reasoning."""

from typing import Literal

from pydantic import Field, StrictStr

from kai_agent.domain.base import BaseModel

MemoryKind = Literal["fact", "preference", "resolution"]


class MemoryProposal(BaseModel):
    action: Literal["add", "update", "forget"]
    memory_id: StrictStr = Field(default="", max_length=128)
    kind: MemoryKind
    content: StrictStr = Field(default="", max_length=2000)
    source_quote: StrictStr = Field(min_length=1, max_length=2000)

    class Config:
        extra = "forbid"


class MemoryUpdate(BaseModel):
    id: str
    action: Literal["add", "update", "forget"]
    kind: MemoryKind
    content: str = Field(min_length=1, max_length=2000)
    before_content: str = Field(default="", max_length=2000)
    expected_revision: int = Field(default=0, ge=0)
    origin: Literal["automatic", "requested", "manual"] = "automatic"
    source_quote: str = Field(default="", max_length=2000)
    source_chat_id: str | None = None
