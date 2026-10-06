from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from klipperai_agent.agent.models import AgentLimits
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.application.chat import ChatService
from klipperai_agent.application.investigations import InvestigationMemory
from klipperai_agent.application.proposal_review import ProposalReviewService
from klipperai_agent.application.sessions import InMemorySessionStore
from klipperai_agent.config.collector import ConfigCollector
from klipperai_agent.diagnostics.collector import DiagnosticsCollector
from klipperai_agent.diagnostics.rules import RuleEngine
from klipperai_agent.infrastructure.host.logs import HostLogCollector
from klipperai_agent.infrastructure.host.system import (
    HostSystemCollector,
    SystemCommandRunner,
)
from klipperai_agent.infrastructure.investigations import SqliteInvestigationRepository
from klipperai_agent.infrastructure.moonraker import MoonrakerClient
from klipperai_agent.profile.saved import build_profile_from_settings
from klipperai_agent.providers.factory import (
    build_config_provider,
    build_diagnosis_provider,
    build_intent_router,
)
from klipperai_agent.providers.responses import OpenAIAgentModel, ResponsesClient
from klipperai_agent.providers.web_search import OpenAIWebSearch
from klipperai_agent.runtime.settings import Settings
from klipperai_agent.workflows.context import WorkflowContext
from klipperai_agent.workflows.engine import build_config_graph, build_diagnosis_graph


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    moonraker: MoonrakerClient
    sessions: InMemorySessionStore
    chat_service: ChatService
    responses: ResponsesClient | None = None

    async def aclose(self) -> None:
        try:
            await self.moonraker.aclose()
        finally:
            if self.responses is not None:
                await self.responses.aclose()


def build_container(settings: Settings) -> AppContainer:
    moonraker = MoonrakerClient(settings.moonraker_url)
    host_logs = None
    if settings.collect_host_logs:
        host_logs = HostLogCollector(
            settings.printer_data_root,
            logs_dir_path=settings.logs_dir_path,
            default_tail_lines=settings.log_tail_lines_default,
            tail_lines_by_log=settings.log_tail_lines_overrides,
            excluded_logs=settings.excluded_logs,
            artifact_char_limit=settings.log_artifact_char_limit,
        )
    host_system = None
    if settings.collect_systemd_diagnostics:
        host_system = HostSystemCollector(
            moonraker_service_name=settings.moonraker_service_name,
            klipper_service_name=settings.klipper_service_name,
            journal_lines=settings.journal_lines,
            status_artifact_char_limit=settings.system_status_artifact_char_limit,
            journal_artifact_char_limit=settings.journal_artifact_char_limit,
            runner=SystemCommandRunner(timeout_seconds=settings.system_command_timeout_seconds),
        )
    collector = DiagnosticsCollector(
        moonraker,
        host_logs=host_logs,
        host_system=host_system,
    )
    rules = RuleEngine()
    diagnosis_provider = build_diagnosis_provider(settings)
    config_provider = build_config_provider(settings)
    intent_router = build_intent_router(settings)
    config_collector = ConfigCollector(
        settings.printer_data_root,
        root_config_name=settings.config_root_file,
        ignore_globs=settings.config_ignore_globs,
        max_documents=100,
        max_chars_per_document=24000,
    )
    profile = build_profile_from_settings(settings)
    workflow_context = WorkflowContext(
        collector=collector,
        rules=rules,
        llm=diagnosis_provider,
        intent_router=intent_router,
        config_collector=config_collector,
        config_llm=config_provider,
        host_logs=host_logs,
        profile=profile,
    )
    diagnosis_graph = build_diagnosis_graph()
    config_graph = build_config_graph()
    sessions = InMemorySessionStore(settings.session_ttl_seconds)
    repository = SqliteInvestigationRepository(
        settings.data_dir,
        protected_dirs=(
            settings.printer_data_root / "config",
            settings.mainsail_config_dir,
            settings.printer_data_root / "gcodes",
            settings.host_logs_dir(),
        ),
        retention_days=settings.memory_retention_days,
    )
    printer_id = sha256(
        f"{settings.moonraker_url}|{settings.printer_data_root.resolve()}|{settings.config_root_file}".encode()
    ).hexdigest()
    investigations = InvestigationMemory(
        repository, printer_id, cross_chat=settings.memory_cross_chat
    )
    responses = None
    agent = None
    if settings.llm_provider == "openai" and settings.agent_enabled:
        responses = ResponsesClient(
            settings.openai_model,
            settings.openai_api_key.get_secret_value() if settings.openai_api_key else None,
            max_output_tokens=settings.agent_max_output_tokens,
        )
        limits = AgentLimits(
            max_steps=settings.agent_max_steps,
            max_tool_calls=settings.agent_max_tool_calls,
            tool_timeout_seconds=settings.agent_tool_timeout_seconds,
            run_timeout_seconds=settings.agent_run_timeout_seconds,
            max_context_chars=settings.agent_max_context_chars,
            max_result_chars=settings.agent_max_result_chars,
        )
        search = (
            OpenAIWebSearch(responses, settings.web_search_domains)
            if settings.web_search_enabled
            else None
        )
        agent = AgentWorkflow(OpenAIAgentModel(responses), moonraker, limits, search)
    chat_service = ChatService(
        provider_name=diagnosis_provider.name,
        root_path=settings.root_path.rstrip("/"),
        diagnosis_graph=diagnosis_graph,
        config_graph=config_graph,
        workflow_context=workflow_context,
        sessions=sessions,
        provider_model=settings.openai_model if diagnosis_provider.name == "openai" else None,
        conversation_history_pairs=settings.conversation_history_pairs,
        agent_workflow=agent,
        investigations=investigations,
        proposal_review=ProposalReviewService(config_collector),
    )
    return AppContainer(
        settings=settings,
        moonraker=moonraker,
        sessions=sessions,
        chat_service=chat_service,
        responses=responses,
    )
