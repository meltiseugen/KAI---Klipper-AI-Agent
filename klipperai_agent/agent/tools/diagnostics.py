"""Read more of an already collected diagnostic, without exposing host paths."""

from typing import Any

from pydantic import Field, StrictStr, conint

from klipperai_agent.agent.tools.base import Tool, ToolArguments, ToolContext
from klipperai_agent.domain.evidence import SourceCitation


class ReadDiagnosticArguments(ToolArguments):
    artifact_id: StrictStr = Field(min_length=1, max_length=80)
    start_line: conint(strict=True, ge=1) = 1  # type: ignore[valid-type]
    line_count: conint(strict=True, ge=1, le=120) = 60  # type: ignore[valid-type]


class ReadDiagnosticTool(Tool[ReadDiagnosticArguments]):
    name = "read_diagnostic_artifact"
    label = "Read diagnostic excerpt"
    description = (
        "Read bounded lines from an artifact ID returned by collect_diagnostics. "
        "Line numbers are within the collected excerpt, not the original log. "
        "Cannot read arbitrary files or older/rotated logs."
    )
    arguments_type = ReadDiagnosticArguments

    async def execute(
        self, arguments: ReadDiagnosticArguments, context: ToolContext
    ) -> dict[str, Any]:
        artifact = context.diagnostic_artifacts.get(arguments.artifact_id)
        if artifact is None:
            return {"error": "Unknown diagnostic ID. Call collect_diagnostics first."}
        lines = artifact.content.splitlines()
        start = arguments.start_line - 1
        if start >= len(lines):
            return {"error": "Line is outside the collected diagnostic excerpt."}
        selected = "\n".join(lines[start : start + arguments.line_count])
        citation = SourceCitation(
            label=f"{artifact.label} (excerpt line {arguments.start_line})",
            path=f"diagnostic:{arguments.artifact_id}",
            line_number=arguments.start_line,
            excerpt=selected[:10000],
        )
        context.citations.append(citation)
        return {
            "source": citation.model_dump(),
            "total_lines": len(lines),
            "truncated": len(selected) > 10000,
            "context_notes": f"{artifact.label}: collected excerpt lines {arguments.start_line}–{min(len(lines), start + arguments.line_count)}. Original log line numbers/time span may differ.",
        }
