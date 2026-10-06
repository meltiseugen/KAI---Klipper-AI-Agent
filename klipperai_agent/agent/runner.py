"""A bounded observe -> act -> observe loop, with request-local evidence and events."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field

from klipperai_agent.agent.models import AgentAnswer, AgentLimits, AgentModel, EventSink
from klipperai_agent.agent.prompts import SYSTEM_PROMPT
from klipperai_agent.agent.registry import ToolRegistry
from klipperai_agent.agent.tools.base import ToolContext
from klipperai_agent.domain.evidence import AgentEvent
from klipperai_agent.domain.investigation import InvestigationRequest, InvestigationResult

logger = logging.getLogger(__name__)


@dataclass
class AgentRun:
    context: ToolContext
    events: list[AgentEvent] = field(default_factory=list)
    answer: AgentAnswer | None = None
    status: str = "completed"

    def result(self) -> InvestigationResult:
        assert self.answer is not None
        citations = {
            (item.path, item.line_number, item.section): item for item in self.context.citations
        }
        return InvestigationResult.parse_obj(
            {
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
    ) -> InvestigationResult:
        run = AgentRun(context)

        async def emit(event: AgentEvent) -> None:
            run.events.append(event)
            if on_event:
                await on_event(event)

        try:
            await asyncio.wait_for(
                self._loop(request, run, registry, emit), self._limits.run_timeout_seconds
            )
        except asyncio.TimeoutError:
            await self._stop(
                run,
                emit,
                "The investigation reached its time limit. Ask a narrower follow-up.",
                "limited",
            )
        except Exception:
            logger.warning("Agent run failed", exc_info=True)
            await self._stop(
                run,
                emit,
                "The model could not complete this investigation. Check provider settings and try again.",
                "error",
            )
        return run.result()

    async def _loop(
        self, request: InvestigationRequest, run: AgentRun, registry: ToolRegistry, emit: EventSink
    ) -> None:
        conversation = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "request": request.user_message,
                        "recent_conversation": request.conversation_context,
                        "historical_evidence": [
                            item.historical_context() for item in request.memory
                        ],
                        "artifacts": [item.model_dump() for item in run.context.artifacts],
                    }
                ),
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
            turn = await self._model.respond(conversation, definitions)
            conversation.extend(turn.output)
            if not turn.calls:
                try:
                    run.answer = AgentAnswer.parse_raw(turn.text)
                    return
                except ValueError:
                    # Allow a bounded repair without treating malformed output as a successful answer.
                    conversation.append(
                        {
                            "role": "user",
                            "content": "Return the final answer as the requested JSON object with a nonempty response.",
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
                        "output": json.dumps(result, ensure_ascii=False),
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
