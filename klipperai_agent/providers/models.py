from __future__ import annotations

from typing import Any, Protocol

from pydantic import Field, validator

from klipperai_agent.config.requests import ConfigPromptPayload
from klipperai_agent.diagnostics.requests import DiagnosisPromptPayload
from klipperai_agent.domain.base import BaseModel
from klipperai_agent.domain.proposals import ConfigProposal
from klipperai_agent.providers.normalization import (
    _coerce_string_list,
    _stringify_llm_item,
)


class DiagnosisLLMOutput(BaseModel):
    summary: str
    likely_causes: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)

    @validator("summary", pre=True)
    def _normalize_summary(cls, value: Any) -> str:
        return _stringify_llm_item(value) or "No diagnosis was returned."

    @validator("likely_causes", "recommended_actions", "follow_up_questions", pre=True)
    def _normalize_string_list(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)


class ConfigAssistantOutput(BaseModel):
    summary: str
    proposals: list[ConfigProposal] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)

    @validator("summary", pre=True)
    def _normalize_summary(cls, value: Any) -> str:
        return _stringify_llm_item(value) or "No config proposal was returned."

    @validator("next_actions", "follow_up_questions", pre=True)
    def _normalize_string_list(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)

    @validator("proposals", pre=True)
    def _normalize_proposals(cls, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return value
        return []


class DiagnosisProvider(Protocol):
    name: str

    async def analyze(self, payload: DiagnosisPromptPayload) -> DiagnosisLLMOutput: ...


class ConfigAssistantProvider(Protocol):
    name: str

    async def propose(self, payload: ConfigPromptPayload) -> ConfigAssistantOutput: ...
