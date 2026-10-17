from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from klipperai_agent.agent.models import EventSink
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.application.intent import (
    ChatIntentOutput,
    classify_deterministic_intent,
    route_for_intent,
)
from klipperai_agent.application.investigations import InvestigationMemory
from klipperai_agent.application.knowledge import PrinterKnowledge
from klipperai_agent.application.proposal_review import ProposalReviewService
from klipperai_agent.application.request_context import (
    _build_chat_artifacts,
    _build_contextual_classification_message,
    _format_conversation_context,
)
from klipperai_agent.application.sessions import InMemorySessionStore
from klipperai_agent.contracts.api import (
    BootstrapResponse,
    ChatRequest,
    ChatResponse,
    MemorySource,
    PrinterProfileSummary,
    UiSessionResponse,
)
from klipperai_agent.domain.context import ModeUnavailableError
from klipperai_agent.domain.investigation import Evidence, InvestigationResult
from klipperai_agent.domain.redaction import redact_data, redact_text
from klipperai_agent.workflows.context import Workflow, WorkflowContext

logger = logging.getLogger("klipperai_agent.chat")


@dataclass(slots=True)
class ChatService:
    provider_name: str
    root_path: str
    diagnosis_graph: Workflow
    config_graph: Workflow
    workflow_context: WorkflowContext
    sessions: InMemorySessionStore
    provider_model: str | None = None
    conversation_history_pairs: int = 10
    agent_workflow: AgentWorkflow | None = None
    investigations: InvestigationMemory | None = None
    proposal_review: ProposalReviewService | None = None
    knowledge: PrinterKnowledge | None = None

    async def create_ui_session(self) -> UiSessionResponse:
        session = self.sessions.create()
        logger.info(
            "Created UI session expires_at=%s",
            session.expires_at.isoformat(),
        )
        return UiSessionResponse(
            session_id=session.session_id,
            embed_path=f"{self.root_path}/embed?session={session.session_id}"
            if self.root_path
            else f"/embed?session={session.session_id}",
            expires_at=session.expires_at,
        )

    async def bootstrap(self, session_id: str) -> BootstrapResponse:
        session = self.sessions.get(session_id)
        if not session:
            logger.warning("Rejected bootstrap for invalid or expired session")
            raise ValueError("Invalid or expired session.")

        moonraker_reachable = await self.workflow_context.collector.ping()
        klipper_reachable = (
            await self.workflow_context.collector.ping_printer() if moonraker_reachable else False
        )
        logger.info(
            "Bootstrap provider=%s provider_model=%s moonraker_reachable=%s klipper_reachable=%s profile=%s",
            self.provider_name,
            self.provider_model or "unavailable",
            moonraker_reachable,
            klipper_reachable,
            self.workflow_context.profile.summary_label() or "unavailable",
        )
        return BootstrapResponse(
            session_id=session_id,
            agent_modes=["chat", "debug"] if self.agent_workflow else [],
            provider=self.provider_name,
            provider_model=self.provider_model,
            conversation_history_pairs=self.conversation_history_pairs,
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
                *(["printer-knowledge"] if self.knowledge else []),
                "addon-detection",
                "typed-findings",
                "local-workflows",
                "conversation-history",
                *(["persistent-investigations"] if self.investigations else []),
                *(["manual-proposal-review"] if self.proposal_review else []),
                "new-chat",
                "intent-routing",
                "context-gated-flows",
                *(["tool-using-agent", "agent-progress"] if self.agent_workflow else []),
                *(
                    ["web-search"]
                    if self.agent_workflow and self.agent_workflow.web_search_enabled
                    else []
                ),
            ],
            printer_profile=PrinterProfileSummary.model_validate(
                redact_data(self.workflow_context.profile.to_summary())
            ),
        )

    async def chat(
        self, payload: ChatRequest, *, on_event: EventSink | None = None
    ) -> ChatResponse:
        session = self.sessions.get(payload.session_id)
        if not session:
            logger.warning("Rejected chat for invalid or expired session")
            raise ValueError("Invalid or expired session.")

        payload = payload.copy(
            update={
                "message": redact_text(payload.message),
                "artifacts": [
                    item.copy(
                        update={
                            "label": redact_text(item.label),
                            "content": redact_text(item.content),
                        }
                    )
                    for item in payload.artifacts
                ],
                "history": [
                    item.copy(update={"text": redact_text(item.text)}) for item in payload.history
                ],
            }
        )

        if payload.mode == "debug" and not self.agent_workflow:
            raise ModeUnavailableError(
                "Debug mode requires the tool-using agent. Enable it with a configured model provider."
            )

        investigation = (
            await self.investigations.open(payload.thread_id, payload.message)
            if self.investigations
            else None
        )
        thread_id = investigation.id if investigation else payload.thread_id or str(uuid4())
        history = (
            investigation.history() if investigation and investigation.turns else payload.history
        )
        memory = (
            await self.investigations.recall(investigation, payload.message)
            if self.investigations and investigation
            else []
        )
        conversation_context = _format_conversation_context(
            history,
            max_pairs=self.conversation_history_pairs,
        )
        classification_message = _build_contextual_classification_message(
            payload.message, conversation_context
        )
        chat_intent = (
            classify_deterministic_intent(payload.message)
            if self.agent_workflow
            else await self._classify_chat_intent(
                payload.message, classification_message=classification_message
            )
        )
        route: str = route_for_intent(chat_intent)
        request_artifacts = _build_chat_artifacts(payload.message, route, payload.artifacts)
        state: dict[str, Any] = {
            "mode": payload.mode,
            "session_id": payload.session_id,
            "thread_id": thread_id,
            "user_message": payload.message,
            "conversation_context": conversation_context,
            "artifacts": [artifact.model_dump() for artifact in request_artifacts],
            "chat_intent": chat_intent.model_dump(),
            "memory": [item.model_dump() for item in memory],
        }
        if memory and not self.agent_workflow:
            state["conversation_context"] += (
                "\nHistorical observations, not current state:\n"
                + json.dumps([item.historical_context() for item in memory])
            )
        graph = self.config_graph if route == "config" else self.diagnosis_graph
        if self.agent_workflow:
            graph = self.agent_workflow
            state["on_event"] = on_event
            route = "agent"
        config = {"configurable": {"thread_id": f"{route}:{thread_id}"}}
        logger.info(
            "Chat request thread_id=%s route=%s message_chars=%s artifacts=%s",
            thread_id,
            route,
            len(payload.message),
            len(request_artifacts),
        )
        try:
            result = await graph.ainvoke(
                state,
                config=config,
                context=self.workflow_context,
            )
        except Exception:
            logger.exception(
                "Chat workflow failed thread_id=%s route=%s",
                thread_id,
                route,
            )
            raise

        outcome = InvestigationResult.parse_obj(result)
        outcome.memory_sources = [
            MemorySource(evidence_id=item.id, source=item.source, observed_at=item.observed_at)
            for item in memory
            if not self.agent_workflow
            or any(
                entry.source == f"memory:{item.id}" and entry.sent_to_model
                for entry in outcome.context_included
            )
        ]
        outcome.evidence.extend(
            Evidence(source=f"user:{item.label}", content=item.content[:16000])
            for item in request_artifacts
        )
        if not self.agent_workflow:
            outcome.evidence.extend(
                Evidence(source=source.path, content=source.excerpt[:16000], citations=[source])
                for source in outcome.source_citations
            )
            outcome.evidence.extend(
                Evidence(
                    source=f"rule:{finding.code}", content=json.dumps(finding.model_dump())[:16000]
                )
                for finding in outcome.findings
            )
        if self.proposal_review:
            await self.proposal_review.review(outcome)
        outcome = InvestigationResult.parse_obj(redact_data(outcome.model_dump()))
        if self.investigations and investigation:
            await self.investigations.remember(
                investigation, payload.message, outcome, payload.history
            )
        logger.info(
            "Chat response thread_id=%s route=%s findings=%s config_proposals=%s patch_proposals=%s source_citations=%s moonraker_reachable=%s",
            thread_id,
            route,
            len(outcome.findings),
            len(outcome.config_proposals),
            len(outcome.patch_proposals),
            len(outcome.source_citations),
            result.get("moonraker_reachable", False),
        )
        return ChatResponse(
            session_id=payload.session_id,
            mode=outcome.mode,
            context_included=outcome.context_included,
            thread_id=thread_id,
            response=outcome.response_text,
            findings=outcome.findings,
            next_actions=outcome.next_actions,
            config_proposals=outcome.config_proposals,
            patch_proposals=outcome.patch_proposals,
            source_citations=outcome.source_citations,
            provider=self.provider_name,
            moonraker_reachable=outcome.moonraker_reachable,
            agent_events=outcome.agent_events,
            agent_status=outcome.agent_status,
            memory_sources=outcome.memory_sources,
        )

    async def _classify_chat_intent(
        self, message: str, *, classification_message: str | None = None
    ) -> ChatIntentOutput:
        deterministic = classify_deterministic_intent(message)

        intent_router = getattr(self.workflow_context, "intent_router", None)
        if intent_router is None:
            return deterministic

        try:
            routed = ChatIntentOutput.model_validate(
                await intent_router.classify(classification_message or message)
            )
        except Exception:
            logger.exception("Intent routing failed; falling back to deterministic route.")
            return deterministic

        if routed.confidence <= 0:
            return deterministic
        return routed
