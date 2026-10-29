"""Request-local workflow contracts; no model intent call or additional capabilities."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field, StrictStr, conint

from klipperai_agent.config.targeting import infer_config_request_target, looks_like_config_request
from klipperai_agent.domain.base import BaseModel
from klipperai_agent.domain.investigation import InvestigationRequest
from klipperai_agent.domain.proposals import ConfigFeature

WorkflowKind = Literal["general", "diagnosis", "config_explanation", "config_draft"]


class EvidenceReference(BaseModel):
    evidence_id: StrictStr = Field(min_length=1, max_length=80)
    start_line: conint(strict=True, ge=0) = 0  # type: ignore[valid-type]
    end_line: conint(strict=True, ge=0) = 0  # type: ignore[valid-type]

    class Config:
        extra = "forbid"


class CitedClaim(BaseModel):
    claim: StrictStr = Field(min_length=1, max_length=2000)
    evidence_refs: list[EvidenceReference] = Field(min_items=1, max_items=4)

    class Config:
        extra = "forbid"


class DraftProposal(BaseModel):
    feature: ConfigFeature = "generic"
    title: StrictStr = Field(min_length=1, max_length=240)
    target_file: StrictStr = Field(min_length=1, max_length=240)
    config: StrictStr = Field(min_length=1, max_length=16000)
    rationale: StrictStr = Field(min_length=1, max_length=2000)
    assumptions: list[StrictStr] = Field(default_factory=list, max_items=12)
    warnings: list[StrictStr] = Field(default_factory=list, max_items=12)

    class Config:
        extra = "forbid"


class GeneralAnswer(BaseModel):
    response: StrictStr = Field(min_length=1, max_length=24000)
    next_actions: list[StrictStr] = Field(default_factory=list, max_items=8)
    claims: list[CitedClaim] = Field(default_factory=list, max_items=12)
    missing_evidence: list[StrictStr] = Field(default_factory=list, max_items=8)
    config_proposals: list[DraftProposal] = Field(default_factory=list, max_items=0)

    class Config:
        extra = "forbid"
        anystr_strip_whitespace = True


class DiagnosisAnswer(GeneralAnswer):
    hypotheses: list[StrictStr] = Field(default_factory=list, max_items=8)


class ConfigExplanationAnswer(GeneralAnswer):
    config_scope: Literal["on_disk", "general_reference", "unavailable"] = "on_disk"


class ConfigDraftAnswer(GeneralAnswer):
    config_proposals: list[DraftProposal] = Field(default_factory=list, max_items=5)


_MODELS: dict[WorkflowKind, type[GeneralAnswer]] = {
    "general": GeneralAnswer,
    "diagnosis": DiagnosisAnswer,
    "config_explanation": ConfigExplanationAnswer,
    "config_draft": ConfigDraftAnswer,
}

_GUIDANCE: dict[WorkflowKind, str] = {
    "general": "Answer the question directly. Collect evidence for printer-specific claims. Do not draft configuration.",
    "diagnosis": "Separate observed failure signatures from hypotheses and missing_evidence. Use deterministic findings and their recovery playbooks before proposing manual checks. Do not generate configuration in a diagnosis answer; ask for a separate draft request if needed.",
    "config_explanation": "Locate or explain observed on-disk files and sections with citations. Distinguish active and inactive files and loaded firmware. Do not draft changes.",
    "config_draft": "Draft only the requested configuration. Inspect the target and relevant static/hardware checks first. Keep unknown values as placeholders, list assumptions and warnings, and never claim a draft passed the application's later manual review.",
}


def select_workflow(request: InvestigationRequest) -> WorkflowKind:
    message = request.user_message
    target = infer_config_request_target(message)
    config = looks_like_config_request(message)
    reported_failure = bool(
        re.search(
            r"\b(error|fail(?:ed|ure|ing)?|shutdown|diagnos\w*|debug|fault|problem|crash|stopped|timeout)\b|timer too close|lost communication|not heating|out of range|must home|below minimum temp",
            message,
            re.I,
        )
    )
    if (
        config
        and not reported_failure
        and re.match(r"\s*(?:explain\b|where\b|which file\b|what file\b)", message, re.I)
    ):
        return "config_explanation"
    draft = re.search(
        r"\b(generate|create|draft|propose|proposal|edit|change|modify|replace|rewrite|add|remove|configure|disable|enable|rename|update|improve|optimize)\b",
        message,
        re.I,
    )
    if (
        draft
        and (config or target.feature != "generic")
        and not (reported_failure and re.match(r"\s*(?:why|what|how)\b", message, re.I))
    ):
        return "config_draft"
    if config and not reported_failure and target.intent in {"locate", "explain"}:
        return "config_explanation"
    if (
        request.mode == "debug"
        or any(
            item.kind in {"klippy_log", "moonraker_log", "system_log"} for item in request.artifacts
        )
        or reported_failure
    ):
        return "diagnosis"
    return "general"


def response_model(workflow: WorkflowKind) -> type[GeneralAnswer]:
    return _MODELS[workflow]


def response_format(workflow: WorkflowKind) -> dict[str, Any]:
    def strict(value: Any) -> Any:
        if isinstance(value, list):
            return [strict(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: strict(item) for key, item in value.items() if key != "default"}
        if result.get("type") == "object":
            result["additionalProperties"] = False
            result["required"] = list(result["properties"])
        return result

    return {
        "type": "json_schema",
        "name": f"klipperai_{workflow}",
        "strict": True,
        "schema": strict(response_model(workflow).schema()),
    }


def workflow_prompt(workflow: WorkflowKind) -> str:
    return (
        f"\nSelected workflow: {workflow}. {_GUIDANCE[workflow]}\n"
        "Return only this workflow's JSON response schema. claims contains concise public conclusions, "
        "never hidden reasoning. Cite printer-specific claims using collected evidence_refs: evidence_id "
        "and inclusive start_line/end_line within that artifact's line_basis. Use both lines=0 only "
        "to reference source citations already attached to an artifact. Never invent IDs, paths, "
        "quotes or ranges. Leave claims empty for generic explanations. State missing evidence explicitly."
    )
