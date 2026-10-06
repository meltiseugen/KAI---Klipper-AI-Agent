from __future__ import annotations

from typing import Any

from pydantic import Field, StrictStr

from klipperai_agent.agent.models import WebSearch
from klipperai_agent.agent.tools.base import Tool, ToolArguments, ToolContext


class SearchArguments(ToolArguments):
    query: StrictStr = Field(min_length=3, max_length=500)


class WebSearchTool(Tool[SearchArguments]):
    name = "search_web"
    label = "Search web documentation"
    description = (
        "Search current public documentation. Use generic technical terms; never include secrets, "
        "private log contents, local addresses or serial numbers in a search query."
    )
    arguments_type = SearchArguments

    def __init__(self, search: WebSearch) -> None:
        self._search = search

    async def execute(self, arguments: SearchArguments, context: ToolContext) -> dict[str, Any]:
        result = await self._search.search(arguments.query)
        context.citations.extend(result.citations)
        return {
            "summary": result.summary,
            "sources": [item.model_dump() for item in result.citations],
        }
