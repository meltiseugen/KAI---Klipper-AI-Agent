from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TypedDict

from klipperai_agent.application.intent import IntentRouterProvider
from klipperai_agent.config.collector import ConfigCollector
from klipperai_agent.diagnostics.collector import DiagnosticsCollector
from klipperai_agent.diagnostics.rules import RuleEngine
from klipperai_agent.infrastructure.host.logs import HostLogCollector
from klipperai_agent.profile.models import PrinterProfile
from klipperai_agent.providers.models import ConfigAssistantProvider, DiagnosisProvider


@dataclass(slots=True)
class WorkflowContext:
    collector: DiagnosticsCollector
    rules: RuleEngine
    llm: DiagnosisProvider
    intent_router: IntentRouterProvider | None
    config_collector: ConfigCollector
    config_llm: ConfigAssistantProvider
    host_logs: HostLogCollector | None
    profile: PrinterProfile


@dataclass(slots=True)
class WorkflowRuntime:
    context: WorkflowContext


class Workflow(Protocol):
    async def ainvoke(
        self,
        state: dict[str, Any],
        *,
        config: dict[str, Any] | None = None,
        context: WorkflowContext,
    ) -> dict[str, Any]: ...


class DiagnosisState(TypedDict, total=False):
    session_id: str
    thread_id: str
    user_message: str
    conversation_context: str
    artifacts: list[dict[str, Any]]
    snapshot: dict[str, Any]
    config_snapshot: dict[str, Any]
    findings: list[dict[str, Any]]
    llm_output: dict[str, Any]
    response_text: str
    next_actions: list[str]
    moonraker_reachable: bool
    patch_proposals: list[dict[str, Any]]
    source_citations: list[dict[str, Any]]
    chat_intent: dict[str, Any]


class ConfigState(TypedDict, total=False):
    session_id: str
    thread_id: str
    user_message: str
    conversation_context: str
    artifacts: list[dict[str, Any]]
    feature_target: dict[str, Any]
    config_snapshot: dict[str, Any]
    runtime_snapshot: dict[str, Any]
    config_output: dict[str, Any]
    response_text: str
    next_actions: list[str]
    config_proposals: list[dict[str, Any]]
    source_citations: list[dict[str, Any]]
    chat_intent: dict[str, Any]
