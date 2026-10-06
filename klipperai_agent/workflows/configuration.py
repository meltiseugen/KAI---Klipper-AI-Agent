from __future__ import annotations

from klipperai_agent.config.lookup import build_config_lookup_response
from klipperai_agent.config.models import ConfigRequestTarget, ConfigSnapshot
from klipperai_agent.config.requests import ConfigPromptPayload
from klipperai_agent.config.targeting import (
    infer_config_request_target,
    looks_like_config_content_request,
)
from klipperai_agent.config.vocabulary import ConfigRequestIntent
from klipperai_agent.diagnostics.models import DiagnosticsSnapshot
from klipperai_agent.domain.evidence import ArtifactInput
from klipperai_agent.domain.proposals import ConfigProposal
from klipperai_agent.workflows.citations import _build_config_source_citations
from klipperai_agent.workflows.context import ConfigState, WorkflowRuntime
from klipperai_agent.workflows.text import _dedupe_items, _looks_like_macro_target


def _config_target_from_chat_intent(state: ConfigState) -> ConfigRequestTarget | None:
    chat_intent = state.get("chat_intent", {})
    intent_name = str(chat_intent.get("intent", "")).strip()
    if intent_name not in {"config_lookup", "config_explain", "edit_existing_config"}:
        return None

    target_section = str(chat_intent.get("target_section") or "").strip().strip("[]")
    if target_section:
        detected = infer_config_request_target(f"Which file has [{target_section}]?")
    else:
        target_text = str(chat_intent.get("target") or "").strip()
        if not target_text:
            intent_map: dict[str, ConfigRequestIntent] = {
                "config_lookup": "locate",
                "config_explain": "explain",
                "edit_existing_config": "edit",
            }
            return ConfigRequestTarget(
                feature="generic",
                rationale=chat_intent.get("rationale")
                or "Follow-up config request with no explicit target.",
                intent=intent_map.get(intent_name, "locate"),
                section_name=None,
            )
        prompt = (
            f"Where is {target_text} macro defined?"
            if _looks_like_macro_target(target_text)
            else f"Where is {target_text} defined?"
        )
        detected = infer_config_request_target(prompt)

    if intent_name == "config_explain":
        return ConfigRequestTarget(
            feature=detected.feature,
            rationale=chat_intent.get("rationale") or detected.rationale,
            intent="explain",
            section_name=detected.section_name,
        )

    if intent_name == "edit_existing_config":
        return ConfigRequestTarget(
            feature=detected.feature,
            rationale=chat_intent.get("rationale") or detected.rationale,
            intent="edit",
            section_name=detected.section_name,
        )

    return detected


def detect_config_target(state: ConfigState) -> ConfigState:
    target = _config_target_from_chat_intent(state) or infer_config_request_target(
        state["user_message"]
    )
    return {
        "feature_target": {
            "feature": target.feature,
            "rationale": target.rationale,
            "intent": target.intent,
            "section_name": target.section_name,
        }
    }


async def collect_config_context(
    state: ConfigState,
    runtime: WorkflowRuntime,
) -> ConfigState:
    target_data = state.get("feature_target", {})
    include_unincluded_configs = target_data.get("intent") in {"locate", "explain", "edit"}
    snapshot = runtime.context.config_collector.collect_with_options(
        include_unincluded_configs=include_unincluded_configs
    )
    input_artifacts = [ArtifactInput.model_validate(item) for item in state.get("artifacts", [])]
    chat_intent = state.get("chat_intent", {})
    include_runtime_context = bool(
        state.get("include_runtime_context", False) or chat_intent.get("needs_logs", False)
    )
    runtime_snapshot = DiagnosticsSnapshot(
        moonraker_reachable=False,
        moonraker_info=None,
        artifacts=list(input_artifacts),
        notes=[],
    )
    if include_runtime_context and runtime.context.host_logs is not None:
        host_artifacts, host_notes = runtime.context.host_logs.collect()
        runtime_snapshot = DiagnosticsSnapshot(
            moonraker_reachable=False,
            moonraker_info=None,
            artifacts=[*input_artifacts, *host_artifacts],
            notes=host_notes,
        )
    return {
        "artifacts": [artifact.model_dump() for artifact in input_artifacts],
        "config_snapshot": snapshot.to_state(),
        "runtime_snapshot": {
            "moonraker_reachable": runtime_snapshot.moonraker_reachable,
            "moonraker_info": runtime_snapshot.moonraker_info,
            "notes": runtime_snapshot.notes,
            "artifacts": [artifact.model_dump() for artifact in runtime_snapshot.artifacts],
        },
    }


def resolve_config_lookup(state: ConfigState) -> ConfigState:
    target_data = state.get("feature_target", {})
    if target_data.get("intent") not in {"locate", "explain"}:
        return {}

    snapshot = ConfigSnapshot.from_state(state.get("config_snapshot", {}))
    target = ConfigRequestTarget(
        feature=target_data.get("feature", "generic"),
        rationale=target_data.get("rationale", "Matched config lookup request."),
        intent=target_data.get("intent", "locate"),
        section_name=target_data.get("section_name"),
    )
    response_text, next_actions = build_config_lookup_response(
        snapshot,
        target,
        include_content=looks_like_config_content_request(state.get("user_message", "")),
    )
    return {
        "response_text": response_text,
        "next_actions": next_actions,
        "config_proposals": [],
        "source_citations": _build_config_source_citations(state, response_text=response_text),
    }


async def call_config_llm(
    state: ConfigState,
    runtime: WorkflowRuntime,
) -> ConfigState:
    target_data = state.get("feature_target", {})
    snapshot_data = state.get("config_snapshot", {})
    detected = infer_config_request_target(state["user_message"])
    target = ConfigRequestTarget(
        feature=target_data.get("feature", detected.feature),
        rationale=target_data.get("rationale", detected.rationale),
        intent=target_data.get("intent", detected.intent),
        section_name=target_data.get("section_name", detected.section_name),
    )

    snapshot = ConfigSnapshot.from_state(snapshot_data)
    runtime_snapshot_data = state.get("runtime_snapshot", {})
    runtime_artifacts = [
        ArtifactInput.model_validate(item) for item in runtime_snapshot_data.get("artifacts", [])
    ]
    runtime_snapshot = DiagnosticsSnapshot(
        moonraker_reachable=bool(runtime_snapshot_data.get("moonraker_reachable", False)),
        moonraker_info=runtime_snapshot_data.get("moonraker_info"),
        artifacts=runtime_artifacts,
        notes=list(runtime_snapshot_data.get("notes", [])),
    )
    payload = ConfigPromptPayload(
        user_message=state["user_message"],
        conversation_context=state.get("conversation_context", ""),
        snapshot=snapshot,
        target=target,
        runtime_snapshot=runtime_snapshot,
        profile=runtime.context.profile,
    )
    config_output = await runtime.context.config_llm.propose(payload)
    return {"config_output": config_output.model_dump()}


def compose_config_response(state: ConfigState) -> ConfigState:
    output = state.get("config_output", {})
    summary = output.get("summary", "No config proposal was generated.")
    proposals = [ConfigProposal.model_validate(item) for item in output.get("proposals", [])]
    next_actions = _dedupe_items(output.get("next_actions", []), limit=2)
    follow_up_questions = list(output.get("follow_up_questions", []))

    lines = [summary]

    if proposals:
        lines.append("")
        lines.append("Proposal:")
        for proposal in proposals[:2]:
            lines.append(f"- {proposal.title} -> {proposal.target_file}")

    if next_actions:
        lines.append("")
        lines.append("Next:")
        for item in next_actions:
            lines.append(f"- {item}")

    if follow_up_questions and not next_actions:
        lines.append("")
        lines.append("Need:")
        for item in follow_up_questions[:1]:
            lines.append(f"- {item}")

    response_text = "\n".join(lines).strip()
    return {
        "response_text": response_text,
        "next_actions": next_actions,
        "config_proposals": [proposal.model_dump() for proposal in proposals],
        "source_citations": _build_config_source_citations(state, response_text=response_text),
    }


def route_config_request(state: ConfigState) -> str:
    return "lookup_done" if state.get("response_text") else "call_llm"
