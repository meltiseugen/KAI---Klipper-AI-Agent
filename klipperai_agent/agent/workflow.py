from __future__ import annotations

from typing import Any

from klipperai_agent.agent.models import AgentLimits, AgentModel, WebSearch
from klipperai_agent.agent.ports import (
    FileMetadataReader,
    KnowledgeReader,
    PrinterReader,
    ShutdownReader,
    ToolServices,
)
from klipperai_agent.agent.registry import ToolRegistry
from klipperai_agent.agent.runner import AgentRunner
from klipperai_agent.agent.tools.base import Tool, ToolContext
from klipperai_agent.agent.tools.config import InspectConfigTool, ReadConfigTool
from klipperai_agent.agent.tools.config_search import SearchConfigTool
from klipperai_agent.agent.tools.diagnostics import ReadDiagnosticTool
from klipperai_agent.agent.tools.file_metadata import FileMetadataTool
from klipperai_agent.agent.tools.knowledge import (
    EddyCalibrationTool,
    FanPortsTool,
    PrinterKnowledgeTool,
    SearchKnowledgeTool,
)
from klipperai_agent.agent.tools.objects import PrinterObjectsTool
from klipperai_agent.agent.tools.printer import (
    DiagnosticsTool,
    PrinterProfileTool,
    PrinterStatusTool,
)
from klipperai_agent.agent.tools.search import WebSearchTool
from klipperai_agent.agent.tools.shutdown import ShutdownTool
from klipperai_agent.domain.evidence import ArtifactInput
from klipperai_agent.domain.investigation import InvestigationRequest


class AgentWorkflow:
    """Adapts the agent to the same application port as local offline workflows."""

    def __init__(
        self,
        model: AgentModel,
        moonraker: PrinterReader,
        limits: AgentLimits,
        search: WebSearch | None = None,
        shutdown_reader: ShutdownReader | None = None,
        knowledge: KnowledgeReader | None = None,
        file_metadata: FileMetadataReader | None = None,
    ) -> None:
        self._runner = AgentRunner(model, limits)
        self._moonraker = moonraker
        self._limits = limits
        self._search = search
        self._shutdown_reader = shutdown_reader
        self._knowledge = knowledge
        self._file_metadata = file_metadata

    @property
    def web_search_enabled(self) -> bool:
        return self._search is not None

    async def ainvoke(
        self,
        state: dict[str, Any],
        *,
        config: dict[str, Any] | None = None,
        context: ToolServices,
    ) -> dict[str, Any]:
        tools: list[Tool] = [
            PrinterProfileTool(),
            PrinterStatusTool(),
            InspectConfigTool(),
            ReadConfigTool(),
            DiagnosticsTool(),
            SearchConfigTool(),
            ReadDiagnosticTool(),
            PrinterObjectsTool(),
        ]
        if self._search is not None:
            tools.append(WebSearchTool(self._search))
        if self._file_metadata is not None:
            tools.append(FileMetadataTool(self._file_metadata))
        if self._shutdown_reader is not None:
            tools.append(ShutdownTool(self._shutdown_reader))
        if self._knowledge is not None:
            tools.extend(
                [
                    PrinterKnowledgeTool(self._knowledge),
                    SearchKnowledgeTool(self._knowledge),
                    FanPortsTool(self._knowledge),
                    EddyCalibrationTool(self._knowledge),
                ]
            )
        tool_context = ToolContext(
            services=context,
            moonraker=self._moonraker,
            artifacts=[ArtifactInput.model_validate(item) for item in state.get("artifacts", [])],
        )
        result = await self._runner.run(
            InvestigationRequest.parse_obj(state),
            tool_context,
            ToolRegistry(tools, self._limits),
            state.get("on_event"),
            state.get("on_checkpoint"),
        )
        return result.model_dump()
