"""Deterministic starting evidence, bounded independently of later model tool calls."""

from __future__ import annotations

import json
import re
from typing import Any

from klipperai_agent.agent.context_budget import fit_result
from klipperai_agent.agent.deadline import within
from klipperai_agent.agent.models import AgentLimits, EventSink, ToolCall
from klipperai_agent.agent.prompts import SYSTEM_PROMPT
from klipperai_agent.agent.registry import ToolRegistry
from klipperai_agent.agent.tools.base import ToolContext
from klipperai_agent.diagnostics.evidence import config_evidence
from klipperai_agent.domain.artifacts import normalize_input
from klipperai_agent.domain.context import ContextItem, ContextStatus
from klipperai_agent.domain.evidence import AgentEvent, SourceCitation
from klipperai_agent.domain.investigation import Evidence, InvestigationRequest, utc_now


async def prepare_context(
    request: InvestigationRequest,
    context: ToolContext,
    registry: ToolRegistry,
    limits: AgentLimits,
    emit: EventSink,
) -> dict[str, Any]:
    supplied = [normalize_input(item) for item in context.artifacts]
    context.evidence.extend(Evidence.parse_obj(item.model_dump()) for item in supplied)
    payload: dict[str, Any] = {
        "mode": request.mode,
        "request": request.user_message,
        "recent_conversation": request.conversation_context,
        "historical_evidence": [item.historical_context() for item in request.memory],
        "artifacts": [item.model_dump() for item in supplied],
    }
    for source, content, detail in [
        (
            "Conversation history",
            request.conversation_context,
            "Previous messages may include diagnostics from an earlier mode.",
        ),
        *[
            (
                f"memory:{item.id}",
                item.content,
                f"Historical observation from {item.source}, observed {item.observed_at}; not a confirmed current fact.",
            )
            for item in request.memory
        ],
        *[
            (
                f"user:{item.label}",
                item.content,
                "User-supplied evidence, not automatically verified.",
            )
            for item in context.artifacts
        ],
    ]:
        if content:
            context.context_included.append(
                ContextItem(
                    source=source, detail=detail, characters=len(content), observed_at=utc_now()
                )
            )
    # Reserve room for the system prompt, the answer and follow-up tool results.
    remaining = max(
        0, (limits.max_context_chars - len(SYSTEM_PROMPT) - len(json.dumps(payload))) // 2 - 500
    )
    if remaining < 2000:
        payload["context_notes"] = (
            "Starting printer context omitted because request/history leaves insufficient context budget. Relevant read-only tools remain available."
        )
        context.context_included.append(
            ContextItem(
                source="Starting printer context",
                status="omitted",
                detail="Request/history leaves insufficient context budget. Ask a narrower question or start a new chat.",
                observed_at=utc_now(),
            )
        )
        return payload

    async def read(name: str, arguments: dict[str, Any], budget: int) -> dict[str, Any]:
        label = registry.label(name)
        await emit(AgentEvent(kind="tool_started", tool=name, message=label))
        result = await registry.execute(
            ToolCall(f"initial:{name}", name, json.dumps(arguments)), context, initial=True
        )
        model_result = registry.model_result(name)
        fitted = fit_result(model_result, max(150, budget))
        if fitted is not model_result:
            receipt = context.context_included[-1]
            if receipt.status != "unavailable":
                receipt.status = "partial"
            receipt.detail += (
                " Starting-context budget truncated this result; tools can request more."
            )
            receipt.characters = len(json.dumps(fitted))
        await emit(
            AgentEvent(
                kind="tool_error" if "error" in result else "tool_completed",
                tool=name,
                message=f"{label}: unavailable" if "error" in result else f"{label}: complete",
            )
        )
        return fitted

    payload["saved_profile"] = await read("get_printer_profile", {}, min(4000, remaining // 5))
    remaining -= len(json.dumps(payload["saved_profile"]))
    if any(tool["name"] == "get_printer_knowledge" for tool in registry.definitions()):
        payload["printer_knowledge"] = await read(
            "get_printer_knowledge", {}, min(5000, remaining // 4)
        )
        remaining -= len(json.dumps(payload["printer_knowledge"]))
    # Leave a separate allowance for diagnostics. Config never displaces it.
    config_budget = max(0, remaining // 2)
    await emit(
        AgentEvent(kind="tool_started", tool="inspect_config", message="Load active configuration")
    )
    payload["active_config"] = await _config_context(
        context, config_budget, limits.tool_timeout_seconds
    )
    remaining -= len(json.dumps(payload["active_config"]))
    await emit(
        AgentEvent(
            kind="tool_error" if "error" in payload["active_config"] else "tool_completed",
            tool="inspect_config",
            message="Active configuration checked",
        )
    )
    debug = request.mode == "debug"
    if debug:
        payload["live_status"] = await read("get_printer_status", {}, remaining // 3)
        remaining -= len(json.dumps(payload["live_status"]))
    has_shutdown = debug and any(
        tool["name"] == "investigate_shutdown" for tool in registry.definitions()
    )
    payload["diagnostics"] = await read(
        "collect_diagnostics",
        {"include_logs": True, "include_system": debug},
        remaining // 3 if has_shutdown else remaining,
    )
    remaining -= len(json.dumps(payload["diagnostics"]))
    if has_shutdown and re.search(
        r"communication|timing|timer too close|shutdown|stopped|timeout.*homing|timer in the past",
        request.user_message + json.dumps(payload["diagnostics"]),
        re.I,
    ):
        payload["shutdown_investigation"] = await read("investigate_shutdown", {}, remaining)
    return payload


async def _config_context(context: ToolContext, budget: int, timeout: float) -> dict[str, Any]:
    try:
        snapshot = await within(context.config(), timeout)
    except Exception:
        context.context_included.append(
            ContextItem(
                source="Active configuration",
                status="unavailable",
                observed_at=utc_now(),
                detail="Could not collect active configuration. Do not infer that the configuration is empty.",
            )
        )
        return {"error": "Active configuration unavailable."}
    result: dict[str, Any] = {
        "root_file": snapshot.root_file,
        "revision": snapshot.revision(),
        "notes": [note[:300] for note in snapshot.notes[:10]],
        "files": [],
        "scope": "Files reachable from the configured root include tree; runtime may still use an older configuration.",
    }
    context.context_included.append(
        ContextItem(
            source="Active configuration",
            observed_at=utc_now(),
            status="included" if snapshot.documents else "unavailable",
            detail=("; ".join(snapshot.notes) or "Read root configuration and includes.")[:2000],
        )
    )
    remaining = max(0, budget - len(json.dumps(result)) - 30)
    omitted = 0
    normalized_files = config_evidence(snapshot)
    for document, observation in zip(snapshot.documents, normalized_files):
        full = {
            "path": document.path,
            "content": observation.content,
            "truncated": observation.status == "partial",
        }
        full["artifact"] = observation.prompt_metadata()
        size = max(len(json.dumps(full)), len(document.content)) + 2
        status: ContextStatus = "partial" if document.truncated else "included"
        detail = (
            "Collected file excerpt; collector truncated this file."
            if document.truncated
            else "Full file from the root include tree."
        )
        if size > remaining:
            full = {"path": document.path, "sections": document.sections, "content_omitted": True}
            full["artifact"] = {**observation.prompt_metadata(), "status": "partial"}
            size = len(json.dumps(full)) + 2
            status = "partial"
            detail = "Section index only. Use inspect_config or read_config_file for content."
        if size > remaining:
            status = "omitted"
            omitted += 1
            detail = "Context budget reached. Use inspect_config to list this file."
        else:
            result["files"].append(full)
            remaining -= size
            if "content" in full:
                citation = SourceCitation(
                    label=document.path,
                    path=document.path,
                    line_number=1,
                    excerpt=document.content[:1000],
                )
                context.citations.append(citation)
                context.evidence.append(observation)
        context.context_included.append(
            ContextItem(
                source=document.path,
                status=status,
                detail=detail,
                observed_at=utc_now(),
                characters=0 if status == "omitted" else size,
            )
        )
    result["omitted_files"] = omitted
    return result
