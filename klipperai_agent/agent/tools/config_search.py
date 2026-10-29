"""Literal search across collected configuration, including macro references."""

from bisect import bisect_right
from typing import Any

from pydantic import Field, StrictBool, StrictStr

from klipperai_agent.agent.tools.base import Tool, ToolContext
from klipperai_agent.agent.tools.text_search import LiteralSearchArguments, line_matches, match_page
from klipperai_agent.config.models import ConfigReadError
from klipperai_agent.domain.evidence import SourceCitation


class SearchConfigArguments(LiteralSearchArguments):
    include_unincluded: StrictBool = False
    path: StrictStr = Field(default="", max_length=240)
    section: StrictStr = Field(default="", max_length=160)


class SearchConfigTool(Tool[SearchConfigArguments]):
    name = "search_config"
    label = "Search configuration"
    description = (
        "Search literal text (case-insensitive, not regex) across the collected config tree. "
        "Find pins, options, macro definitions and references with source lines and context. "
        "Optionally filter by an exact collected path or section. Use whole_word for exact "
        "pin/identifier matches, case_sensitive if needed, and offset for later matches. "
        "Matches include comments; they are not proof that a macro executes. "
        "Additional unincluded files are explicitly marked."
    )
    arguments_type = SearchConfigArguments

    async def execute(
        self, arguments: SearchConfigArguments, context: ToolContext
    ) -> dict[str, Any]:
        query = arguments.query.strip()
        if not query:
            return {"error": "Enter nonblank search text."}
        snapshot = await context.config(arguments.include_unincluded)
        active = {doc.path for doc in context.snapshots[False].documents}
        if arguments.path and not any(doc.path == arguments.path for doc in snapshot.documents):
            return {
                "error": "File is not in the collected config tree. Use inspect_config for exact available paths."
            }
        notes = list(snapshot.notes)
        documents = []
        unavailable = False
        for reference in snapshot.documents:
            if arguments.path and reference.path != arguments.path:
                continue
            if arguments.section and not any(
                section.casefold() == arguments.section.strip("[] ").casefold()
                for section in reference.sections
            ):
                continue
            try:
                doc = await context.document(reference.path, arguments.include_unincluded)
            except ConfigReadError as exc:
                notes.append(f"{reference.path}: {exc}")
                unavailable = True
                continue
            assert doc is not None
            documents.append(doc)

        def matches():
            for doc in documents:
                locations = sorted(
                    (item for item in snapshot.section_locations if item.path == doc.path),
                    key=lambda item: item.line_number,
                )
                section_lines = [item.line_number for item in locations]
                for hit in line_matches(
                    doc.content,
                    query,
                    case_sensitive=arguments.case_sensitive,
                    whole_word=arguments.whole_word,
                    context_lines=arguments.context_lines,
                ):
                    section_index = bisect_right(section_lines, hit.line) - 1
                    section = locations[section_index].section if section_index >= 0 else None
                    if (
                        arguments.section
                        and (section or "").casefold() != arguments.section.strip("[] ").casefold()
                    ):
                        continue
                    citation = SourceCitation(
                        label=f"{doc.path}:{hit.start_line}",
                        path=doc.path,
                        line_number=hit.start_line,
                        end_line=hit.end_line,
                        section=section,
                        excerpt=hit.excerpt,
                        line_basis="file",
                    )
                    yield {
                        "source": citation.model_dump(),
                        "match_line": hit.line,
                        "in_active_tree": doc.path in active,
                        "excerpt_truncated": hit.truncated,
                    }

        result = match_page(matches(), arguments.offset, arguments.max_matches)
        context.citations.extend(
            SourceCitation.parse_obj(item["source"]) for item in result["matches"]
        )
        return {
            **result,
            "files_searched": [doc.path for doc in documents],
            "notes": notes,
            "truncated": result["truncated"] or unavailable,
            "scope": "Collected configuration text only; comments and inactive references may match.",
        }
