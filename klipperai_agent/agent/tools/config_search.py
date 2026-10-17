"""Literal search across collected configuration, including macro references."""

from typing import Any

from pydantic import Field, StrictBool, StrictStr, conint

from klipperai_agent.agent.tools.base import Tool, ToolArguments, ToolContext
from klipperai_agent.domain.evidence import SourceCitation


class SearchConfigArguments(ToolArguments):
    query: StrictStr = Field(min_length=1, max_length=160)
    include_unincluded: StrictBool = False
    max_matches: conint(strict=True, ge=1, le=20) = 10  # type: ignore[valid-type]


class SearchConfigTool(Tool[SearchConfigArguments]):
    name = "search_config"
    label = "Search configuration"
    description = (
        "Search literal text (case-insensitive, not regex) across the collected config tree. "
        "Find pins, options, macro definitions and references with source lines. "
        "Matches include comments; they are not proof that a macro executes. "
        "Additional unincluded files are explicitly marked."
    )
    arguments_type = SearchConfigArguments

    async def execute(
        self, arguments: SearchConfigArguments, context: ToolContext
    ) -> dict[str, Any]:
        query = arguments.query.strip().casefold()
        if not query:
            return {"error": "Enter nonblank search text."}
        snapshot = await context.config(arguments.include_unincluded)
        active = {doc.path for doc in context.snapshots[False].documents}
        matches: list[dict[str, Any]] = []
        count = 0
        clipped = False
        for reference in snapshot.documents:
            doc = await context.document(reference.path, arguments.include_unincluded)
            assert doc is not None
            for number, line in enumerate(doc.content.splitlines(), 1):
                if query not in line.casefold():
                    continue
                count += 1
                if len(matches) >= arguments.max_matches:
                    continue
                clipped = clipped or len(line) > 400
                citation = SourceCitation(
                    label=f"{doc.path}:{number}",
                    path=doc.path,
                    line_number=number,
                    excerpt=line[:400],
                )
                context.citations.append(citation)
                matches.append(
                    {"source": citation.model_dump(), "in_active_tree": doc.path in active}
                )
        return {
            "matches": matches,
            "total_matches": count,
            "truncated": clipped or count > len(matches),
            "notes": snapshot.notes,
            "scope": "Collected configuration text only; comments and inactive references may match.",
        }
