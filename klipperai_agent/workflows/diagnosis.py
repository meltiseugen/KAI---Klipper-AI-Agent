from __future__ import annotations

from klipperai_agent.config.models import ConfigSnapshot
from klipperai_agent.diagnostics.models import DiagnosticsSnapshot
from klipperai_agent.diagnostics.requests import DiagnosisPromptPayload
from klipperai_agent.domain.evidence import ArtifactInput, IssueFinding
from klipperai_agent.workflows.context import DiagnosisState, WorkflowRuntime
from klipperai_agent.workflows.text import _dedupe_items


async def collect_context(
    state: DiagnosisState,
    runtime: WorkflowRuntime,
) -> DiagnosisState:
    input_artifacts = [ArtifactInput.model_validate(item) for item in state.get("artifacts", [])]
    chat_intent = state.get("chat_intent", {})
    include_runtime_context = bool(chat_intent.get("needs_logs", True))
    snapshot = await runtime.context.collector.collect(
        input_artifacts,
        include_host_logs=include_runtime_context,
        include_host_system=include_runtime_context,
    )
    config_snapshot = runtime.context.config_collector.collect()
    return {
        "artifacts": [artifact.model_dump() for artifact in input_artifacts],
        "snapshot": {
            "moonraker_reachable": snapshot.moonraker_reachable,
            "moonraker_info": snapshot.moonraker_info,
            "notes": snapshot.notes,
            "artifacts": [artifact.model_dump() for artifact in snapshot.artifacts],
        },
        "config_snapshot": config_snapshot.to_state(),
        "moonraker_reachable": snapshot.moonraker_reachable,
    }


async def run_rules(
    state: DiagnosisState,
    runtime: WorkflowRuntime,
) -> DiagnosisState:
    snapshot_data = state.get("snapshot", {})
    artifact_items = snapshot_data.get("artifacts", state.get("artifacts", []))
    artifacts = [ArtifactInput.model_validate(item) for item in artifact_items]
    config_snapshot = ConfigSnapshot.from_state(state.get("config_snapshot", {}))
    findings = runtime.context.rules.analyze(artifacts, config_snapshot=config_snapshot)
    return {
        "findings": [finding.model_dump() for finding in findings],
        "patch_proposals": [],
    }


async def call_llm(
    state: DiagnosisState,
    runtime: WorkflowRuntime,
) -> DiagnosisState:
    snapshot_data = state.get("snapshot", {})
    artifact_items = snapshot_data.get("artifacts", state.get("artifacts", []))
    artifacts = [ArtifactInput.model_validate(item) for item in artifact_items]
    findings = [IssueFinding.model_validate(item) for item in state.get("findings", [])]
    snapshot = DiagnosticsSnapshot(
        moonraker_reachable=bool(snapshot_data.get("moonraker_reachable", False)),
        moonraker_info=snapshot_data.get("moonraker_info"),
        artifacts=artifacts,
        notes=list(snapshot_data.get("notes", [])),
    )
    config_snapshot = ConfigSnapshot.from_state(state.get("config_snapshot", {}))
    payload = DiagnosisPromptPayload(
        user_message=state["user_message"],
        conversation_context=state.get("conversation_context", ""),
        snapshot=snapshot,
        config_snapshot=config_snapshot,
        findings=findings,
        profile=runtime.context.profile,
    )
    llm_output = await runtime.context.llm.analyze(payload)
    return {"llm_output": llm_output.model_dump()}


def compose_response(state: DiagnosisState) -> DiagnosisState:
    findings = state.get("findings", [])
    llm_output = state.get("llm_output", {})
    summary = str(llm_output.get("summary", "No summary available.")).strip()
    likely_causes = llm_output.get("likely_causes", [])
    recommended_actions = llm_output.get("recommended_actions", [])
    follow_up_questions = llm_output.get("follow_up_questions", [])

    lines = [summary]

    if findings:
        primary_finding = findings[0]
        source = str(primary_finding.get("source", "")).strip()
        if source and source not in summary:
            lines.append(f"Location: {source}")
    elif likely_causes:
        primary_cause = str(likely_causes[0]).strip()
        if primary_cause and primary_cause not in summary:
            lines.append(f"Most likely: {primary_cause}")

    concise_actions = _dedupe_items(recommended_actions, limit=2)
    if concise_actions:
        lines.append("")
        lines.append("Fix:")
        for item in concise_actions:
            lines.append(f"- {item}")
    elif not findings and follow_up_questions:
        lines.append("")
        lines.append("Need:")
        for item in follow_up_questions[:1]:
            lines.append(f"- {item}")

    fallback_actions = [finding["proposed_fix"] for finding in findings[:2]]
    next_actions = concise_actions or _dedupe_items(fallback_actions, limit=2)
    return {
        "response_text": "\n".join(lines).strip(),
        "next_actions": next_actions,
    }
