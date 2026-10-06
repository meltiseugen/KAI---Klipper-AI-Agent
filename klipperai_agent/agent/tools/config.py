from __future__ import annotations

from typing import Any

from pydantic import Field, StrictBool, StrictStr

from klipperai_agent.agent.tools.base import Tool, ToolArguments, ToolContext
from klipperai_agent.config.models import ConfigRequestTarget
from klipperai_agent.domain.evidence import SourceCitation


class InspectConfigArguments(ToolArguments):
    section: StrictStr = Field(default="", max_length=160)
    include_unincluded: StrictBool = False


class InspectConfigTool(Tool[InspectConfigArguments]):
    name = "inspect_config"
    label = "Inspect printer configuration"
    description = (
        "List config files and sections, or read an exact section such as 'gcode_macro START_PRINT'. "
        "Set include_unincluded only to search additional files that may not be active."
    )
    arguments_type = InspectConfigArguments

    async def execute(
        self, arguments: InspectConfigArguments, context: ToolContext
    ) -> dict[str, Any]:
        snapshot = await context.config(arguments.include_unincluded)
        result: dict[str, Any] = {"root_file": snapshot.root_file, "notes": snapshot.notes}
        if not arguments.section:
            result["files"] = [
                {"path": doc.path, "sections": doc.sections} for doc in snapshot.documents
            ]
            return result
        target = ConfigRequestTarget(
            "generic", "Agent section lookup", "locate", arguments.section.strip("[]")
        )
        matches = snapshot.find_section_locations(target, limit=8)
        citations = [
            SourceCitation(
                label=location.summary(),
                path=location.path,
                line_number=location.line_number,
                section=location.section,
                excerpt=(snapshot.section_block(location) or "")[:8000],
            )
            for location in matches
        ]
        context.citations.extend(citations)
        result["sections"] = [citation.model_dump() for citation in citations]
        return result


class ReadConfigArguments(ToolArguments):
    path: StrictStr = Field(min_length=1, max_length=240)
    start_line: int = Field(default=1, ge=1)
    line_count: int = Field(default=80, ge=1, le=160)
    include_unincluded: StrictBool = False


class ReadConfigTool(Tool[ReadConfigArguments]):
    name = "read_config_file"
    label = "Read config file"
    description = "Read a bounded range of lines from an exact path returned by inspect_config. No arbitrary host paths."
    arguments_type = ReadConfigArguments

    async def execute(self, arguments: ReadConfigArguments, context: ToolContext) -> dict[str, Any]:
        snapshot = await context.config(arguments.include_unincluded)
        document = next((doc for doc in snapshot.documents if doc.path == arguments.path), None)
        if document is None:
            return {
                "error": "File is not in the collected config tree. Call inspect_config for available paths."
            }
        lines = document.content.splitlines()
        start = arguments.start_line - 1
        if start >= len(lines):
            return {
                "error": "Requested line is outside the collected excerpt.",
                "notes": snapshot.notes,
            }
        excerpt = "\n".join(lines[start : start + arguments.line_count])[:10000]
        citation = SourceCitation(
            label=f"{document.path}:{arguments.start_line}",
            path=document.path,
            line_number=arguments.start_line,
            excerpt=excerpt,
        )
        context.citations.append(citation)
        return {"source": citation.model_dump(), "total_lines": len(lines), "notes": snapshot.notes}
