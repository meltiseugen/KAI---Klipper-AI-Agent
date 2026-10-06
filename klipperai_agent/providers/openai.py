from __future__ import annotations

from klipperai_agent.application.intent import ChatIntentOutput
from klipperai_agent.config.requests import ConfigPromptPayload
from klipperai_agent.diagnostics.requests import DiagnosisPromptPayload
from klipperai_agent.providers.json_client import OpenAIJsonClient
from klipperai_agent.providers.models import ConfigAssistantOutput, DiagnosisLLMOutput
from klipperai_agent.providers.normalization import (
    _CONFIG_FEATURE_VALUES,
    _normalize_config_assistant_data,
    _with_required_summary,
)


class OpenAIDiagnosisProvider:
    name = "openai"

    def __init__(self, model: str, api_key: str | None) -> None:
        self._client = OpenAIJsonClient(model=model, api_key=api_key)

    async def analyze(self, payload: DiagnosisPromptPayload) -> DiagnosisLLMOutput:
        findings_block = "\n".join(
            (
                f"- [{finding.severity}] {finding.summary} | source: {finding.source} "
                f"| evidence: {finding.evidence} | fix: {finding.proposed_fix}"
            )
            for finding in payload.findings
        )
        if not findings_block:
            findings_block = "No deterministic findings."

        data = await self._client.complete_json(
            system_prompt=(
                "You are an expert Klipper and Moonraker diagnostics assistant. "
                "Use supplied evidence first, do not invent printer state, keep the answer grounded, "
                "and propose safe next steps before any invasive change. "
                "When the current user request is a short follow-up, use the recent conversation to resolve what it refers to. "
                "Use the detected printer profile to avoid assuming the wrong firmware flavor, probe, MCU, or addon stack. "
                "Be extremely brief: lead with the most likely root cause in 1-2 short sentences, cite config-relative file paths and lines when the evidence includes them, "
                "limit likely_causes to 1 item, limit recommended_actions to at most 2 short items, avoid background explanation, and only ask follow-up questions when the diagnosis is blocked by missing evidence. "
                "Return only JSON with keys: summary, likely_causes, recommended_actions, follow_up_questions."
            ),
            user_prompt=(
                f"User request:\n{payload.user_message}\n\n"
                f"Recent conversation:\n{payload.conversation_context or 'No prior conversation context.'}\n\n"
                f"Detected printer profile:\n{payload.profile.to_prompt_block()}\n\n"
                f"Collected context:\n{payload.snapshot.to_prompt_block()}\n\n"
                f"Current config context:\n{payload.config_snapshot.to_prompt_block()}\n\n"
                f"Deterministic findings:\n{findings_block}\n\n"
                "Return a concise structured diagnosis with exact file references when available."
            ),
        )
        return DiagnosisLLMOutput.model_validate(
            _with_required_summary(data, "No diagnosis was returned.")
        )


class OpenAIIntentRouterProvider:
    name = "openai"

    def __init__(self, model: str, api_key: str | None) -> None:
        self._client = OpenAIJsonClient(model=model, api_key=api_key)

    async def classify(self, message: str) -> ChatIntentOutput:
        data = await self._client.complete_json(
            system_prompt=(
                "You classify short KlipperAI user requests into exactly one intent. "
                "Choose config_lookup for finding/showing where an existing config section or macro is defined. "
                "Choose config_explain for explaining what an existing config section or macro does, where it is used, or what calls it. "
                "Choose diagnose_issue only when the user reports a failure, error, shutdown, broken behavior, or asks why something is not working. "
                "Choose generate_config when the user asks to create or draft new config. "
                "Choose edit_existing_config when the user asks to change, remove, rename, enable, or disable existing config. "
                "Choose general only when none of those apply. "
                "If the request includes recent conversation, classify only the current user message, using the prior turns to resolve short follow-ups like 'do that'. "
                "Set needs_logs true only for diagnose_issue or when the user pasted log/error context. "
                "For macro targets, set target_section to gcode_macro MACRO_NAME, for example gcode_macro SFS_ENABLE. "
                "Return only JSON with keys: intent, target, target_section, needs_logs, confidence, rationale."
            ),
            user_prompt=f"User request:\n{message}\n\nClassify this request.",
        )
        return ChatIntentOutput.model_validate(data)


class OpenAIConfigAssistantProvider:
    name = "openai"

    def __init__(self, model: str, api_key: str | None) -> None:
        self._client = OpenAIJsonClient(model=model, api_key=api_key)

    async def propose(self, payload: ConfigPromptPayload) -> ConfigAssistantOutput:
        data = await self._client.complete_json(
            system_prompt=(
                "You are an expert Klipper and Kalico configuration assistant. "
                "When the current user request is a short follow-up, use the recent conversation to resolve what it refers to. "
                "For locate or explain requests, answer the user's question directly from the supplied config context instead of generating a snippet. "
                "For locate requests, lead with the exact config-relative file path and line number when present. "
                "Use config-relative paths exactly as shown in the supplied config context; do not expand them to absolute host paths. "
                "Do not add a separate sources list to the summary; the UI will show source citations below the answer. "
                "If an exact section is not present, say that plainly and mention close matches or additional collected files only when the evidence supports it. "
                "If a file is marked as additional lookup context, explain that it may not be active unless included. "
                "For generate or edit requests, generate safe, reviewable config snippets only and prefer managed include snippets under klipperai/*.cfg. "
                "Do not imply that you can write files or apply changes directly. "
                "Do not invent existing pins or hardware details. If details are missing, use placeholders and list the assumptions clearly. "
                "Use the detected printer profile to tailor suggestions to the printer's firmware flavor, MCU layout, and installed addons. "
                "Keep summary and next actions brief. "
                "Return only JSON with keys: summary, proposals, next_actions, follow_up_questions. "
                "For locate or explain requests, proposals should usually be an empty list. "
                "Each proposal, when present, must include: feature, title, target_file, config, rationale, assumptions, warnings. "
                f"The feature must be one of: {', '.join(_CONFIG_FEATURE_VALUES)}. "
                "Use generic for include directives, config-file organization, or any proposal that does not fit a listed printer feature."
            ),
            user_prompt=(
                f"User request:\n{payload.user_message}\n\n"
                f"Recent conversation:\n{payload.conversation_context or 'No prior conversation context.'}\n\n"
                f"Detected printer profile:\n{payload.profile.to_prompt_block()}\n\n"
                f"Detected target:\n{payload.target.feature}\n"
                f"Detected request mode:\n{payload.target.intent}\n"
                f"Detection rationale:\n{payload.target.rationale}\n\n"
                f"Collected runtime context:\n{payload.runtime_snapshot.to_prompt_block() if payload.runtime_snapshot else 'No runtime context collected.'}\n\n"
                f"Current config context:\n{payload.snapshot.to_prompt_block()}\n\n"
                "Return a concise structured config proposal."
            ),
        )
        normalized_data = _normalize_config_assistant_data(
            _with_required_summary(data, "No config proposal was returned."),
            fallback_feature=payload.target.feature,
        )
        return ConfigAssistantOutput.model_validate(normalized_data)
