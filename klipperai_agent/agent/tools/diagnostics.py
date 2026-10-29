"""Read more of an already collected diagnostic, without exposing host paths."""

from typing import Any

from pydantic import Field, StrictStr, conint

from klipperai_agent.agent.tools.base import Tool, ToolArguments, ToolContext
from klipperai_agent.agent.tools.text_search import LiteralSearchArguments, line_matches, match_page
from klipperai_agent.domain.evidence import SourceCitation
from klipperai_agent.domain.redaction import redact_text


class SearchDiagnosticArguments(LiteralSearchArguments):
    artifact_ids: list[StrictStr] = Field(default_factory=list, max_items=12)


class SearchDiagnosticTool(Tool[SearchDiagnosticArguments]):
    name = "search_diagnostic_artifacts"
    label = "Search collected diagnostics"
    description = "Find literal text with context in diagnostic artifact IDs from collect_diagnostics, including collected service journals. No new commands or filesystem reads. Lines refer to the collected excerpt, not original log lines."
    arguments_type = SearchDiagnosticArguments

    async def execute(
        self, arguments: SearchDiagnosticArguments, context: ToolContext
    ) -> dict[str, Any]:
        query = arguments.query.strip()
        if not query:
            return {"error": "Enter nonblank search text."}
        ids = set(arguments.artifact_ids)
        if ids - context.diagnostic_artifacts.keys() or not context.diagnostic_artifacts:
            return {
                "error": "Unknown or missing diagnostic artifacts. Call collect_diagnostics first."
            }

        def matches():
            for identifier, artifact in context.diagnostic_artifacts.items():
                if ids and identifier not in ids:
                    continue
                for hit in line_matches(
                    redact_text(artifact.content),
                    query,
                    case_sensitive=arguments.case_sensitive,
                    whole_word=arguments.whole_word,
                    context_lines=arguments.context_lines,
                ):
                    citation = SourceCitation(
                        label=f"{artifact.label} (excerpt lines {hit.start_line}–{hit.end_line})",
                        path=f"diagnostic:{identifier}",
                        line_number=hit.start_line,
                        end_line=hit.end_line,
                        excerpt=hit.excerpt,
                        line_basis="excerpt",
                    )
                    yield {
                        "artifact_id": identifier,
                        "match_line": hit.line,
                        "source": citation.model_dump(),
                        "excerpt_truncated": hit.truncated,
                    }

        result = match_page(matches(), arguments.offset, arguments.max_matches)
        context.citations.extend(
            SourceCitation.parse_obj(item["source"]) for item in result["matches"]
        )
        return {
            **result,
            "scope": "Previously collected diagnostic excerpts only; missing or older events may be outside these excerpts.",
        }


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
