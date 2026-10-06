from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, validator

from klipperai_agent.domain.base import BaseModel


class ChatHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=8000)

    @validator("text", pre=True)
    def _normalize_text(cls, value: Any) -> str:
        return str(value or "").strip()
