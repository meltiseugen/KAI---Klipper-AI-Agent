"""The registry is the only boundary through which the model can run local tools."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic import ValidationError

from klipperai_agent.agent.deadline import within
from klipperai_agent.agent.models import AgentLimits, ToolCall
from klipperai_agent.agent.tools.base import Tool, ToolContext
from klipperai_agent.config.models import ConfigReadError
from klipperai_agent.domain.artifacts import normalize_artifact
from klipperai_agent.domain.context import ContextItem
from klipperai_agent.domain.investigation import Evidence, utc_now
from klipperai_agent.domain.redaction import redact_data

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self, tools: list[Tool], limits: AgentLimits) -> None:
        self._tools = {tool.name: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("Duplicate tool name.")
        self._limits = limits
        self._cache: dict[str, dict[str, Any]] = {}
        self._observations: dict[str, Evidence] = {}
        self._recorded: dict[tuple[str, str], Evidence] = {}

    def definitions(self) -> list[dict[str, Any]]:
        return [tool.definition() for tool in self._tools.values()]

    def label(self, name: str) -> str:
        tool = self._tools.get(name)
        return tool.label if tool else "Unknown tool"

    async def execute(
        self, call: ToolCall, context: ToolContext, *, initial: bool = False
    ) -> dict[str, Any]:
        citation_start = len(context.citations)
        result = await self._execute(call, context)
        observation_key = (call.name, json.dumps(result, ensure_ascii=False))
        existing = self._recorded.get(observation_key)
        if existing is None:
            active = context.snapshots.get(False)
            artifact = normalize_artifact(
                source=call.name,
                label=self.label(call.name),
                content=result,
                kind="printer_profile"
                if call.name == "get_printer_profile"
                else "printer_status"
                if call.name in {"get_printer_status", "get_printer_objects"}
                else "reference"
                if call.name == "search_web"
                else "shutdown_report"
                if call.name == "investigate_shutdown"
                else "tool_result",
                origin="config"
                if call.name
                in {"inspect_config", "read_config_file", "search_config", "analyze_config"}
                else "host"
                if call.name in {"list_logs", "search_logs", "read_log_excerpt"}
                else "saved_profile"
                if call.name == "get_printer_profile"
                else "web"
                if call.name == "search_web"
                else "tool",
                freshness="saved_configuration"
                if call.name
                in {
                    "get_printer_profile",
                    "inspect_config",
                    "read_config_file",
                    "search_config",
                    "analyze_config",
                }
                else "reference"
                if call.name == "search_web"
                else "historical"
                if call.name in {"investigate_shutdown", "search_logs", "read_log_excerpt"}
                else "current_snapshot",
                unavailable="error" in result,
                partial=bool(result.get("truncated")),
                config_revision=active.revision() if active else None,
                citations=context.citations[citation_start:],
            )
            context.evidence.append(Evidence.parse_obj(artifact.model_dump()))
            existing = context.evidence[-1]
            self._recorded[observation_key] = existing
            # Enrich trusted tool citations with the observation that retained them.
            for citation in existing.citations:
                if citation.line_number:
                    citation.line_basis = (
                        "file"
                        if existing.origin == "config"
                        else "excerpt"
                        if call.name == "read_diagnostic_artifact"
                        else citation.line_basis
                    )
                    citation.end_line = citation.end_line or (
                        citation.line_number + max(0, len(citation.excerpt.splitlines()) - 1)
                    )
            context.citations[citation_start:] = existing.citations
        self._observations[call.name] = existing
        detail = str(result.get("error") or result.get("context_notes") or self.label(call.name))
        if "error" in result and result.get("notes"):
            detail += " " + "; ".join(str(note) for note in result["notes"][:5])
        context.context_included.append(
            ContextItem(
                source=call.name,
                status="unavailable"
                if "error" in result
                else "partial"
                if existing.status == "partial"
                else "included",
                detail=detail[:2000],
                characters=len(json.dumps(self.model_result(call.name), ensure_ascii=False)),
                observed_at=utc_now(),
                phase="initial" if initial else "tool",
            )
        )
        return result

    def model_result(self, name: str) -> dict[str, Any]:
        observation = self._observations[name]
        if observation.content_format == "json":
            return {**json.loads(observation.content), "_artifact": observation.prompt_metadata()}
        return {
            "excerpt": observation.content,
            "truncated": True,
            "_artifact": observation.prompt_metadata(),
        }

    async def _execute(self, call: ToolCall, context: ToolContext) -> dict[str, Any]:
        tool = self._tools.get(call.name)
        if tool is None:
            return {"error": "Unknown or disabled tool."}
        try:
            if len(call.arguments) > 6000:
                return {"error": "Tool arguments exceed the size limit."}
            data = json.loads(call.arguments)
            if not isinstance(data, dict):
                return {"error": "Tool arguments must be a JSON object."}
            arguments = tool.arguments_type.parse_obj(data)
        except (ValueError, ValidationError):
            return {"error": "Invalid tool arguments. Check the tool schema and retry."}
        key = call.name + json.dumps(arguments.model_dump(), sort_keys=True)
        if key in self._cache:
            return self._cache[key]
        try:
            result = await within(
                tool.execute(arguments, context),
                self._limits.tool_timeout_seconds,
            )
        except asyncio.TimeoutError:
            return {"error": "Tool timed out. Continue with other evidence or ask a follow-up."}
        except ConfigReadError as exc:
            return {"error": str(exc)}
        except Exception:
            logger.warning("Tool execution failed: %s", tool.name, exc_info=True)
            return {"error": "Tool unavailable. Do not assume that evidence was collected."}
        try:
            result = redact_data(result)
            serialized = json.dumps(result, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            return {"error": "Tool returned an invalid observation; evidence is unavailable."}
        if len(serialized) > self._limits.max_result_chars:
            result = {"truncated": True, "excerpt": serialized[: self._limits.max_result_chars]}
        if "error" not in result:
            self._cache[key] = result
        return result
