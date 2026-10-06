"""The registry is the only boundary through which the model can run local tools."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic import ValidationError

from klipperai_agent.agent.models import AgentLimits, ToolCall
from klipperai_agent.agent.tools.base import Tool, ToolContext
from klipperai_agent.domain.investigation import Evidence

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self, tools: list[Tool], limits: AgentLimits) -> None:
        self._tools = {tool.name: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("Duplicate tool name.")
        self._limits = limits
        self._cache: dict[str, dict[str, Any]] = {}

    def definitions(self) -> list[dict[str, Any]]:
        return [tool.definition() for tool in self._tools.values()]

    def label(self, name: str) -> str:
        tool = self._tools.get(name)
        return tool.label if tool else "Unknown tool"

    async def execute(self, call: ToolCall, context: ToolContext) -> dict[str, Any]:
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
            result = await asyncio.wait_for(
                tool.execute(arguments, context),
                timeout=self._limits.tool_timeout_seconds,
            )
        except asyncio.TimeoutError:
            return {"error": "Tool timed out. Continue with other evidence or ask a follow-up."}
        except Exception:
            logger.warning("Tool execution failed: %s", tool.name, exc_info=True)
            return {"error": "Tool unavailable. Do not assume that evidence was collected."}
        serialized = json.dumps(result, ensure_ascii=False)
        if len(serialized) > self._limits.max_result_chars:
            result = {"truncated": True, "excerpt": serialized[: self._limits.max_result_chars]}
        if "error" not in result:
            self._cache[key] = result
            active = context.snapshots.get(False)
            revision = active.revision() if active is not None else None
            context.evidence.append(
                Evidence(
                    source=call.name,
                    content=json.dumps(result, ensure_ascii=False)[:16000],
                    config_revision=revision,
                    citations=list(context.citations),
                )
            )
        return result
