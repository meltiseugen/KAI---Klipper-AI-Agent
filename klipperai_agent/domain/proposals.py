from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import Field, validator

from klipperai_agent.domain.base import BaseModel

ConfigFeature = Literal[
    "fan",
    "macro",
    "sensor",
    "probe",
    "heater",
    "input_shaper",
    "bed_mesh",
    "filament",
    "canbus",
    "stepper",
    "extruder",
    "generic",
]


class PatchProposal(BaseModel):
    target_file: str
    summary: str
    diff: str
    rationale: str
    safe_mode: str = "review"


class ProposalReview(BaseModel):
    proposal_id: str
    reviewed_at: str
    status: Literal["needs_information", "manual_review", "stale"]
    mode: Literal["manual_only"] = "manual_only"
    baseline_revision: str
    observed_revision: str
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    comparison: str = ""


class ConfigProposal(BaseModel):
    feature: ConfigFeature = "generic"
    title: str
    target_file: str
    config: str
    rationale: str
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    review: ProposalReview | None = None

    @validator("assumptions", "warnings", pre=True)
    def _normalize_string_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if not isinstance(value, (list, tuple)):
            value = [value]

        normalized: list[str] = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, str):
                text = item.strip()
            elif isinstance(item, dict):
                text = _stringify_dict(item)
            else:
                text = str(item).strip()
            if text:
                normalized.append(text)
        return normalized


def _stringify_dict(value: dict[Any, Any]) -> str:
    for key in ("summary", "text", "message", "description", "value"):
        nested = value.get(key)
        if nested is not None:
            text = str(nested).strip()
            if text:
                return text
    try:
        return json.dumps(value, sort_keys=True)
    except TypeError:
        return str(value)
