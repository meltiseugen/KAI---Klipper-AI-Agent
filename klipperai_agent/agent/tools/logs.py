"""Discover, search and expand log evidence through a read-only capability."""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import Field, StrictBool, StrictStr, conint

from klipperai_agent.agent.ports import LogReader
from klipperai_agent.agent.tools.base import Tool, ToolArguments, ToolContext
from klipperai_agent.agent.tools.text_search import LiteralSearchArguments, line_matches, match_page
from klipperai_agent.domain.evidence import SourceCitation
from klipperai_agent.domain.logs import (
    LOG_INFLATE_BYTES,
    LOG_RUN_BYTES,
    LOG_RUN_WINDOWS,
    LOG_WINDOW_BYTES,
    LogFile,
    LogInventory,
    LogReadError,
    LogWindow,
)


async def log_inventory(
    reader: LogReader, context: ToolContext, refresh: bool = False
) -> LogInventory:
    if context.log_inventory is None or refresh:
        context.log_inventory = await asyncio.to_thread(reader.inventory)
        if refresh:
            context.log_windows.clear()
    return context.log_inventory


async def log_window(
    reader: LogReader, reference: LogFile, before: int | None, context: ToolContext
) -> LogWindow:
    key = f"{reference.id}:{before}"
    if key not in context.log_windows:
        allowance = LOG_INFLATE_BYTES if reference.compressed else LOG_WINDOW_BYTES
        if (
            len(context.log_windows) >= LOG_RUN_WINDOWS
            or context.log_bytes_reserved + allowance > LOG_RUN_BYTES
        ):
            raise LogReadError(
                "Investigation log-read budget reached. Narrow the sources or start a new investigation."
            )
        # Failed/cancelled reads still consume allowance. Refresh cannot reset it.
        context.log_bytes_reserved += allowance
        context.log_windows[key] = await asyncio.to_thread(reader.read_window, reference, before)
    return context.log_windows[key]


def window_metadata(window: LogWindow) -> dict:
    return {
        "excerpt_id": window.id,
        "log_id": window.log_id,
        "name": window.name,
        "start_byte": window.start_byte,
        "end_byte": window.end_byte,
        "next_before_byte": window.next_before_byte,
        "compressed": window.compressed,
        "partial": window.partial,
        "observed_at": window.observed_at,
        "digest": window.digest,
        "digest_scope": "redacted window, not entire log",
        "line_basis": "excerpt" if window.start_byte else "file",
    }


def log_citation(window: LogWindow, start: int, end: int, excerpt: str) -> SourceCitation:
    return SourceCitation(
        label=f"{window.name} ({'window' if window.start_byte else 'file'} lines {start}–{end})",
        path=f"log:{window.name}",
        line_number=start,
        end_line=end,
        excerpt=excerpt,
        line_basis="excerpt" if window.start_byte else "file",
        observed_at=window.observed_at,
        source_digest=window.digest,
    )


class ListLogsArguments(ToolArguments):
    refresh: StrictBool = False


class ListLogsTool(Tool[ListLogsArguments]):
    name = "list_logs"
    label = "List available printer logs"
    description = (
        "List up to 16 eligible current/recent log files and opaque log IDs. "
        "Exclusions and read-only filesystem restrictions apply. Refresh after rotation. "
        "No paths, commands or write actions are accepted."
    )
    arguments_type = ListLogsArguments

    def __init__(self, reader: LogReader):
        self.reader = reader

    async def execute(self, arguments: ListLogsArguments, context: ToolContext) -> dict[str, Any]:
        inventory = await log_inventory(self.reader, context, arguments.refresh)
        return {
            "files": [
                {
                    "log_id": item.id,
                    "name": item.name,
                    "size_bytes": item.size_bytes,
                    "modified_at": item.modified_at,
                    "compressed": item.compressed,
                    "rotated": item.rotated,
                }
                for item in inventory.files
            ],
            "notes": inventory.notes,
            "truncated": inventory.truncated,
            "scope": "Configured log directory only; no recursive or arbitrary host-file access.",
        }


class SearchLogsArguments(LiteralSearchArguments):
    log_ids: list[StrictStr] = Field(default_factory=list, max_items=4)
    include_rotated: StrictBool = False
    before_byte: conint(strict=True, ge=0, le=2**63 - 1) | None = None  # type: ignore[valid-type]


class SearchLogsTool(Tool[SearchLogsArguments]):
    name = "search_logs"
    label = "Search printer logs"
    description = (
        "Find literal text with surrounding lines in bounded log windows. Use list_logs IDs "
        "to select at most four files; otherwise search up to four current logs. "
        "include_rotated also allows recent rotations in automatic selection. "
        "For older uncompressed data pass a single log ID and its next_before_byte. "
        "offset paginates matches in the same windows; read_log_excerpt expands a match. "
        "No regex, shell or arbitrary paths. No match is not proof the event never occurred."
    )
    arguments_type = SearchLogsArguments

    def __init__(self, reader: LogReader):
        self.reader = reader

    async def execute(self, arguments: SearchLogsArguments, context: ToolContext) -> dict[str, Any]:
        query = arguments.query.strip()
        if not query:
            return {"error": "Enter nonblank search text."}
        inventory = await log_inventory(self.reader, context)
        ids = set(arguments.log_ids)
        if ids - {item.id for item in inventory.files}:
            return {"error": "Unknown log ID. Use list_logs; file paths are not accepted."}
        files = (
            [item for item in inventory.files if item.id in ids]
            if ids
            else [
                item for item in inventory.files if arguments.include_rotated or not item.rotated
            ][:4]
        )
        if arguments.before_byte is not None and len(files) != 1:
            return {"error": "An older byte cursor requires exactly one log ID."}
        if not files:
            return {
                "error": "No eligible log files are available in the configured scope.",
                "notes": inventory.notes,
            }
        notes = list(inventory.notes)
        windows = []
        for reference in files:
            try:
                windows.append(
                    await log_window(self.reader, reference, arguments.before_byte, context)
                )
            except LogReadError as exc:
                notes.append(f"{reference.name}: {exc}")
        if not windows:
            return {"error": "No selected log window could be read.", "notes": notes}

        def matches():
            for window in windows:
                for hit in line_matches(
                    window.content,
                    query,
                    case_sensitive=arguments.case_sensitive,
                    whole_word=arguments.whole_word,
                    context_lines=arguments.context_lines,
                ):
                    yield {
                        "excerpt_id": window.id,
                        "log_id": window.log_id,
                        "match_line": hit.line,
                        "source": log_citation(
                            window, hit.start_line, hit.end_line, hit.excerpt
                        ).model_dump(),
                        "excerpt_truncated": hit.truncated,
                    }

        result = match_page(matches(), arguments.offset, arguments.max_matches)
        context.citations.extend(
            SourceCitation.parse_obj(item["source"]) for item in result["matches"]
        )
        return {
            **result,
            "windows": [window_metadata(item) for item in windows],
            "notes": notes,
            "truncated": result["truncated"]
            or bool(notes)
            or any(item.partial for item in windows)
            or (not ids and len(files) < len(inventory.files)),
            "context_notes": "Only listed windows were searched. Byte limits, excluded/older files and incomplete lines may hide events. Window line numbers are not absolute log lines unless line_basis is file. Appends after inventory are excluded; file changes in place are not a verified historical snapshot.",
        }


class ReadLogArguments(ToolArguments):
    excerpt_id: StrictStr = Field(min_length=1, max_length=80)
    start_line: conint(strict=True, ge=1, le=500000) = 1  # type: ignore[valid-type]
    line_count: conint(strict=True, ge=1, le=120) = 40  # type: ignore[valid-type]


class ReadLogTool(Tool[ReadLogArguments]):
    name = "read_log_excerpt"
    label = "Read around a log match"
    description = "Read lines from a cached excerpt_id returned by search_logs. Use its window-local line numbers. Reads no additional files and accepts no paths or commands."
    arguments_type = ReadLogArguments

    async def execute(self, arguments: ReadLogArguments, context: ToolContext) -> dict[str, Any]:
        window = next(
            (item for item in context.log_windows.values() if item.id == arguments.excerpt_id), None
        )
        if window is None:
            return {
                "error": "Unknown excerpt ID. Search logs first; refreshed inventories invalidate old excerpts."
            }
        lines = window.content.splitlines()
        start = arguments.start_line - 1
        if start >= len(lines):
            return {"error": "Line is outside this cached log window."}
        selected = "\n".join(line[:500] for line in lines[start : start + arguments.line_count])
        excerpt = selected[:8000]
        end = start + len(excerpt.splitlines())
        citation = log_citation(window, arguments.start_line, end, excerpt)
        context.citations.append(citation)
        return {
            "source": citation.model_dump(),
            "window": window_metadata(window),
            "total_lines": len(lines),
            "truncated": len(selected) > 8000
            or any(len(line) > 500 for line in lines[start : start + arguments.line_count]),
            "context_notes": "Cached redacted log evidence; not a fresh read or a complete time window. Long lines/ranges may be clipped.",
        }
