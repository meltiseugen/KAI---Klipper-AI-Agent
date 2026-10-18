"""Session bootstrap and advertised UI capabilities."""

from __future__ import annotations

import logging

from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.application.sessions import InMemorySessionStore
from klipperai_agent.contracts.api import BootstrapResponse, PrinterProfileSummary
from klipperai_agent.domain.redaction import redact_data
from klipperai_agent.workflows.context import WorkflowContext

logger = logging.getLogger("klipperai_agent.chat")


async def bootstrap_response(
    session_id: str,
    *,
    sessions: InMemorySessionStore,
    context: WorkflowContext,
    provider_name: str,
    provider_model: str | None,
    conversation_history_pairs: int,
    agent_workflow: AgentWorkflow | None,
    persistent: bool,
    manual_review: bool,
    knowledge: bool,
) -> BootstrapResponse:
    session = sessions.get(session_id)
    if not session:
        logger.warning("Rejected bootstrap for invalid or expired session")
        raise ValueError("Invalid or expired session.")

    moonraker_reachable = await context.collector.ping()
    klipper_reachable = await context.collector.ping_printer() if moonraker_reachable else False
    logger.info(
        "Bootstrap provider=%s provider_model=%s moonraker_reachable=%s klipper_reachable=%s profile=%s",
        provider_name,
        provider_model or "unavailable",
        moonraker_reachable,
        klipper_reachable,
        context.profile.summary_label() or "unavailable",
    )
    return BootstrapResponse(
        session_id=session_id,
        agent_modes=["chat", "debug"] if agent_workflow else [],
        provider=provider_name,
        provider_model=provider_model,
        conversation_history_pairs=conversation_history_pairs,
        moonraker_reachable=moonraker_reachable,
        klipper_reachable=klipper_reachable,
        expires_at=session.expires_at,
        features=[
            "diagnostics",
            "config-assistant",
            "current-config-inspection",
            "single-question-input",
            "read-only-mode",
            "host-log-collection",
            "systemd-diagnostics",
            "printer-profile",
            *(["printer-knowledge"] if knowledge else []),
            "addon-detection",
            "typed-findings",
            "local-workflows",
            "conversation-history",
            *(
                ["persistent-investigations", "confirmed-memory", "investigation-recovery"]
                if persistent
                else []
            ),
            *(["manual-proposal-review"] if manual_review else []),
            "new-chat",
            "intent-routing",
            "context-gated-flows",
            *(["tool-using-agent", "agent-progress"] if agent_workflow else []),
            *(["web-search"] if agent_workflow and agent_workflow.web_search_enabled else []),
        ],
        printer_profile=PrinterProfileSummary.model_validate(
            redact_data(context.profile.to_summary())
        ),
    )
