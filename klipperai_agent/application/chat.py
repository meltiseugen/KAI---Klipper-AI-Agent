from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from klipperai_agent.agent.models import EventSink
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.application.chat_bootstrap import bootstrap_response
from klipperai_agent.application.chat_response import chat_response
from klipperai_agent.application.intent import (
    ChatIntentOutput,
    classify_deterministic_intent,
    route_for_intent,
)
from klipperai_agent.application.investigations import InvestigationMemory
from klipperai_agent.application.knowledge import PrinterKnowledge
from klipperai_agent.application.proposal_review import ProposalReviewService
from klipperai_agent.application.recovery import with_lease
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
    UiSessionResponse,
)
from klipperai_agent.domain.artifacts import normalize_input
from klipperai_agent.domain.context import ModeUnavailableError
from klipperai_agent.domain.investigation import (
    Evidence,
    Investigation,
    InvestigationResult,
    PendingInvestigation,
)
from klipperai_agent.domain.model_usage import ModelUsage
from klipperai_agent.domain.redaction import redact_data, redact_text
from klipperai_agent.domain.repositories import InvestigationConflict
from klipperai_agent.runtime.model_usage import track_model_usage
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
    provider_ready: bool = True
    conversation_history_pairs: int = 10
    agent_workflow: AgentWorkflow | None = None
    investigations: InvestigationMemory | None = None
    proposal_review: ProposalReviewService | None = None
    knowledge: PrinterKnowledge | None = None
    _run_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

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
        return await bootstrap_response(
            session_id,
            sessions=self.sessions,
            context=self.workflow_context,
            provider_name=self.provider_name,
            provider_model=self.provider_model,
            conversation_history_pairs=self.conversation_history_pairs,
            agent_workflow=self.agent_workflow,
            persistent=self.investigations is not None,
            manual_review=self.proposal_review is not None,
            knowledge=self.knowledge is not None,
        )

    async def chat(
        self, payload: ChatRequest, *, on_event: EventSink | None = None
    ) -> ChatResponse:
        if self._run_lock.locked():
            raise InvestigationConflict(
                "Another investigation is already running on this printer host. Wait for it to finish, then retry."
            )
        async with self._run_lock:
            return await self._chat(payload, on_event=on_event)

    async def _chat(
        self, payload: ChatRequest, *, on_event: EventSink | None = None
    ) -> ChatResponse:
        session = self.sessions.get(payload.session_id)
        if not session:
            logger.warning("Rejected chat for invalid or expired session")
            raise ValueError("Invalid or expired session.")
        if not self.provider_ready:
            raise ModeUnavailableError("Configure an LLM provider and API key to use the agent.")

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
        if self.investigations and investigation:
            owner = str(uuid4())
            await self.investigations.begin(
                investigation,
                PendingInvestigation(
                    message=payload.message,
                    mode=payload.mode,
                    artifacts=payload.artifacts,
                    history=payload.history,
                ),
                owner,
            )
            return await with_lease(
                self.investigations,
                investigation,
                owner,
                self._run(payload, investigation, on_event, owner),
            )
        return await self._run(payload, investigation, on_event)

    async def resume(self, investigation: Investigation, owner: str) -> None:
        assert self.investigations is not None and investigation.pending is not None
        pending = investigation.pending
        payload = ChatRequest(
            session_id="",
            thread_id=investigation.id,
            message=pending.message,
            mode=pending.mode,
            artifacts=pending.artifacts,
            history=pending.history,
        )
        if (
            pending.attempts <= 3
            and self.provider_ready
            and (pending.mode != "debug" or self.agent_workflow)
        ):
            await with_lease(
                self.investigations,
                investigation,
                owner,
                self._resume_run(payload, investigation, owner),
            )
        else:
            await self.investigations.remember(
                investigation,
                pending.message,
                InvestigationResult(
                    model_usage=ModelUsage(status="not_used"),
                    mode=pending.mode,
                    agent_status="limited",
                    evidence=pending.evidence,
                    response_text="Automatic recovery stopped after repeated interruptions or because Debug is unavailable. Review provider settings and send a follow-up to continue.",
                ),
                pending.history,
                owner,
            )

    async def _resume_run(
        self, payload: ChatRequest, investigation: Investigation, owner: str
    ) -> ChatResponse:
        # Recovery keeps its lease alive while waiting for an interactive run.
        async with self._run_lock:
            return await self._run(payload, investigation, None, owner)

    async def _run(
        self,
        payload: ChatRequest,
        investigation: Investigation | None,
        on_event: EventSink | None,
        owner: str | None = None,
    ) -> ChatResponse:
        with track_model_usage(on_event) as usage:
            try:
                return await self._execute(payload, investigation, on_event, owner, usage)
            except Exception as exc:
                setattr(exc, "model_usage", usage.copy(deep=True))
                raise

    async def _execute(
        self,
        payload: ChatRequest,
        investigation: Investigation | None,
        on_event: EventSink | None,
        owner: str | None,
        usage: ModelUsage,
    ) -> ChatResponse:
        thread_id = investigation.id if investigation else payload.thread_id or str(uuid4())
        history = (
            investigation.history() if investigation and investigation.turns else payload.history
        )
        memory = (
            await self.investigations.recall(investigation, payload.message)
            if self.investigations and investigation
            else []
        )
        if investigation and investigation.pending:
            memory += [
                item.copy(update={"content": item.content[:1200]})
                for item in investigation.pending.evidence[-6:]
            ]
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
            if self.investigations and investigation and owner:

                async def checkpoint(evidence: list[Evidence]) -> None:
                    assert self.investigations is not None
                    await self.investigations.checkpoint(investigation, owner, evidence)

                state["on_checkpoint"] = checkpoint
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
        outcome.model_usage = usage.copy(deep=True)
        if investigation and investigation.pending:
            fresh_ids = {item.id for item in outcome.evidence}
            outcome.evidence.extend(
                item.copy(update={"freshness": "historical", "origin": "memory"})
                for item in investigation.pending.evidence
                if item.id not in fresh_ids
            )
        outcome.memory_sources = [
            MemorySource(evidence_id=item.id, source=item.source, observed_at=item.observed_at)
            for item in memory
            if not self.agent_workflow
            or any(
                entry.source == f"memory:{item.id}" and entry.sent_to_model
                for entry in outcome.context_included
            )
        ]
        for item in request_artifacts:
            observation = normalize_input(item)
            if not any(
                existing.source == observation.source and existing.content == observation.content
                for existing in outcome.evidence
            ):
                outcome.evidence.append(Evidence.parse_obj(observation.model_dump()))
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
        outcome.findings.sort(key=lambda item: item.severity_rank, reverse=True)
        if self.investigations and investigation:
            await self.investigations.remember(
                investigation, payload.message, outcome, payload.history, owner
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
        return chat_response(payload.session_id, thread_id, self.provider_name, outcome)

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
