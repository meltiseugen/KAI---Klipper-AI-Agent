"""A bounded observe -> act -> observe loop, with request-local evidence and events."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field

from klipperai_agent.agent.claim_citations import resolve_claims
from klipperai_agent.agent.deadline import within
from klipperai_agent.agent.models import (
    AgentAnswer,
    AgentLimits,
    AgentModel,
    CheckpointSink,
    EventSink,
)
from klipperai_agent.agent.prompts import SYSTEM_PROMPT
from klipperai_agent.agent.registry import ToolRegistry
from klipperai_agent.agent.response_contracts import (
    WorkflowKind,
    response_format,
    response_model,
    select_workflow,
    workflow_prompt,
)
from klipperai_agent.agent.starting_context import prepare_context
from klipperai_agent.agent.tools.base import ToolContext
from klipperai_agent.diagnostics.evidence import link_findings
from klipperai_agent.domain.artifacts import CollectedArtifact
from klipperai_agent.domain.context import AgentMode
from klipperai_agent.domain.evidence import AgentEvent, GroundedClaim
from klipperai_agent.domain.investigation import Evidence, InvestigationRequest, InvestigationResult
from klipperai_agent.domain.provider_settings import ProviderLimitError
from klipperai_agent.domain.redaction import redact_data

logger = logging.getLogger(__name__)


@dataclass
class AgentRun:
    context: ToolContext
    mode: AgentMode = "chat"
    events: list[AgentEvent] = field(default_factory=list)
    answer: AgentAnswer | None = None
    status: str = "completed"
    workflow: WorkflowKind = "general"
    claims: list[GroundedClaim] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)

    def result(self) -> InvestigationResult:
        assert self.answer is not None
        citations = {
            (item.path, item.line_number, item.end_line, item.section): item
            for item in [
                *self.context.citations,
                *(citation for finding in self.context.findings for citation in finding.citations),
                *(citation for claim in self.claims for citation in claim.citations),
            ]
        }
        return InvestigationResult.parse_obj(
            {
                "mode": self.mode,
                "workflow": self.workflow,
                "answer_claims": self.claims,
                "missing_evidence": self.missing_evidence,
                "hypotheses": self.hypotheses,
                "context_included": self.context.context_included,
                "response_text": self.answer.response,
                "next_actions": self.answer.next_actions,
                "config_proposals": [item.model_dump() for item in self.answer.config_proposals],
                "findings": [item.model_dump() for item in self.context.findings],
                "source_citations": [item.model_dump() for item in citations.values()],
                "moonraker_reachable": self.context.moonraker_reachable,
                "agent_events": [event.model_dump() for event in self.events],
                "agent_status": self.status,
                "evidence": self.context.evidence,
            }
        )


class AgentRunner:
    def __init__(self, model: AgentModel, limits: AgentLimits) -> None:
        self._model = model
        self._limits = limits

    async def run(
        self,
        request: InvestigationRequest,
        context: ToolContext,
        registry: ToolRegistry,
        on_event: EventSink | None = None,
        on_checkpoint: CheckpointSink | None = None,
    ) -> InvestigationResult:
        run = AgentRun(context, mode=request.mode, workflow=select_workflow(request))

        async def emit(event: AgentEvent) -> None:
            run.events.append(event)
            if on_checkpoint and event.kind in {"tool_completed", "tool_error"}:
                await on_checkpoint(context.evidence)
            if on_event:
                await on_event(event)

        try:
            await within(self._loop(request, run, registry, emit), self._limits.run_timeout_seconds)
        except asyncio.TimeoutError:
            await self._stop(
                run,
                emit,
                "The investigation reached its time limit. Ask a narrower follow-up.",
                "limited",
            )
        except ProviderLimitError as exc:
            await self._stop(run, emit, str(exc), "limited")
        except Exception:
            logger.warning("Agent run failed", exc_info=True)
            await self._stop(
                run,
                emit,
                "The model could not complete this investigation. Check provider settings and try again.",
                "error",
            )
        return InvestigationResult.parse_obj(redact_data(run.result().model_dump()))

    async def _loop(
        self, request: InvestigationRequest, run: AgentRun, registry: ToolRegistry, emit: EventSink
    ) -> None:
        payload = await prepare_context(request, run.context, registry, self._limits, emit)
        if request.artifacts and not run.context.findings:
            observations: list[CollectedArtifact] = list(run.context.evidence)
            run.context.findings = link_findings(
                run.context.services.rules.analyze(
                    request.artifacts, config_snapshot=run.context.snapshots.get(False)
                ),
                observations,
            )
            known = {item.id for item in run.context.evidence}
            run.context.evidence.extend(
                Evidence.parse_obj(item.model_dump())
                for item in observations
                if item.id not in known
            )
            payload["deterministic_findings"] = [item.model_dump() for item in run.context.findings]
        conversation = [
            {"role": "system", "content": SYSTEM_PROMPT + workflow_prompt(run.workflow)},
            {
                "role": "user",
                "content": json.dumps(redact_data(payload)),
            },
        ]
        used_calls = 0
        call_ids: set[str] = set()
        for _ in range(self._limits.max_steps):
            if len(json.dumps(conversation)) > self._limits.max_context_chars:
                await self._stop(
                    run,
                    emit,
                    "The evidence reached the context limit. Ask a narrower follow-up.",
                    "limited",
                )
                return
            definitions = registry.definitions()
            if used_calls >= self._limits.max_tool_calls:
                definitions = []
                conversation.append(
                    {
                        "role": "user",
                        "content": "The tool budget is exhausted. Return your final JSON answer using the evidence already collected and explain any remaining gaps.",
                    }
                )
            for item in run.context.context_included:
                if item.status != "omitted":
                    item.sent_to_model = True
            turn = await self._model.respond(
                conversation, definitions, response_format=response_format(run.workflow)
            )
            conversation.extend(turn.output)
            if not turn.calls:
                try:
                    parsed = response_model(run.workflow).parse_raw(turn.text)
                    claims = resolve_claims(parsed.claims, run.context.evidence)
                    run.answer = AgentAnswer.parse_obj(parsed.model_dump())
                    run.claims = claims
                    run.missing_evidence = parsed.missing_evidence
                    run.hypotheses = getattr(parsed, "hypotheses", [])
                    return
                except ValueError:
                    # Allow a bounded repair without treating malformed output as a successful answer.
                    conversation.append(
                        {
                            "role": "user",
                            "content": "Return the final answer as the selected workflow's JSON schema with a nonempty response. Use only available evidence IDs and retained line ranges for claims; read missing sources or state the gap. Do not include proposals outside the config_draft workflow or invent review results.",
                        }
                    )
                    continue
            for call in turn.calls:
                if used_calls >= self._limits.max_tool_calls:
                    await self._stop(
                        run,
                        emit,
                        "The investigation reached its tool-call limit. Ask a narrower follow-up.",
                        "limited",
                    )
                    return
                if call.call_id in call_ids:
                    raise ValueError("Provider reused a tool call ID.")
                call_ids.add(call.call_id)
                used_calls += 1
                label = registry.label(call.name)
                await emit(AgentEvent(kind="tool_started", tool=call.name, message=label))
                result = await registry.execute(call, run.context)
                failed = "error" in result
                await emit(
                    AgentEvent(
                        kind="tool_error" if failed else "tool_completed",
                        tool=call.name,
                        message=f"{label}: unavailable" if failed else f"{label}: complete",
                    )
                )
                conversation.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": json.dumps(registry.model_result(call.name), ensure_ascii=False),
                    }
                )
        await self._stop(
            run,
            emit,
            "The investigation reached its step limit. Ask a narrower follow-up.",
            "limited",
        )

    async def _stop(self, run: AgentRun, emit: EventSink, message: str, status: str) -> None:
        run.status = status
        run.answer = AgentAnswer(response=message)
        await emit(AgentEvent(kind="limit" if status == "limited" else "error", message=message))
