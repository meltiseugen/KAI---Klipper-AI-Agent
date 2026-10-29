"""More component families through fixed, read-only configuration/status checks."""

from typing import Any

from pydantic import Field, StrictStr

from klipperai_agent.agent.deadline import within
from klipperai_agent.agent.ports import KnowledgeReader
from klipperai_agent.agent.tools.base import Tool, ToolArguments, ToolContext
from klipperai_agent.agent.tools.knowledge import cite_passages, complete_config
from klipperai_agent.domain.evidence import SourceCitation
from klipperai_agent.knowledge.components import ComponentFamily, inspect_component, matches_family


class ComponentArguments(ToolArguments):
    role: StrictStr = Field(regex=r"^[a-z][a-z0-9_-]{0,39}$")
    family: ComponentFamily


class ComponentDiagnosticTool(Tool[ComponentArguments]):
    name = "inspect_component"
    label = "Inspect component configuration and live evidence"
    description = "Inspect saved accelerometer, probe, TMC driver, temperature or filament sensor evidence using fixed config/status families and reviewed bus sources. No calibration, commands, movement or heater operations. Missing status does not mean healthy hardware."
    arguments_type = ComponentArguments

    def __init__(self, knowledge: KnowledgeReader):
        self._knowledge = knowledge

    async def execute(self, arguments: ComponentArguments, context: ToolContext) -> dict[str, Any]:
        setup, docs, changed = await self._knowledge.read()
        component = next((item for item in setup.components if item.role == arguments.role), None)
        if component is None:
            return {"error": "Identify this component in Printer knowledge first."}
        report = inspect_component(
            setup, docs, component, arguments.family, await complete_config(context), changed
        )
        try:
            available = await within(context.moonraker.list_printer_objects(), 5)
            selected = sorted(name for name in available if matches_family(name, arguments.family))[
                :12
            ]
            report["live_status"] = (
                await within(
                    context.moonraker.query_printer_objects({name: None for name in selected}), 5
                )
                if selected
                else {}
            )
            if not selected:
                report["gaps"].append(
                    "No supported live objects are currently available for this family."
                )
        except Exception:
            report["live_status"] = {}
            report["gaps"].append(
                "Live component status is unavailable; no health conclusion follows."
            )
        cite_passages(report["passages"], context)
        for row in report["configuration"]:
            context.citations.append(
                SourceCitation(
                    label=row["section"],
                    path=row["path"],
                    line_number=row["line"],
                    line_basis="file",
                    excerpt=f"{row['option']}: {row['value']}",
                )
            )
        return report
