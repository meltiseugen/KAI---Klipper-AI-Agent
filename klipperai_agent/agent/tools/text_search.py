"""Pure bounded literal search, shared by config and log evidence tools."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable, Iterator

from pydantic import Field, StrictBool, StrictStr, conint

from klipperai_agent.agent.tools.base import ToolArguments


class LiteralSearchArguments(ToolArguments):
    query: StrictStr = Field(min_length=1, max_length=160)
    case_sensitive: StrictBool = False
    whole_word: StrictBool = False
    context_lines: conint(strict=True, ge=0, le=4) = 1  # type: ignore[valid-type]
    max_matches: conint(strict=True, ge=1, le=20) = 10  # type: ignore[valid-type]
    offset: conint(strict=True, ge=0, le=10000) = 0  # type: ignore[valid-type]


@dataclass(frozen=True)
class LineMatch:
    line: int
    start_line: int
    end_line: int
    excerpt: str
    truncated: bool


def line_matches(
    text: str,
    query: str,
    *,
    case_sensitive: bool = False,
    whole_word: bool = False,
    context_lines: int = 1,
) -> Iterator[LineMatch]:
    # User text is escaped; no user-supplied regex or executable expression.
    literal = re.escape(query)
    pattern = re.compile(
        r"(?<!\w)" + literal + r"(?!\w)" if whole_word else literal,
        0 if case_sensitive else re.IGNORECASE,
    )
    lines = text.splitlines()
    for index, line in enumerate(lines):
        found = pattern.search(line)
        if found is None:
            continue
        start, end = max(0, index - context_lines), min(len(lines), index + context_lines + 1)
        selected = []
        clipped = False
        for number in range(start, end):
            value = lines[number]
            offset = max(0, found.start() - 40) if number == index and len(value) > 240 else 0
            piece = value[offset : offset + 240]
            shortened = offset > 0 or len(value) > offset + 240
            selected.append(
                ("…" if offset else "") + piece + ("…" if len(value) > offset + 240 else "")
            )
            clipped |= shortened
        yield LineMatch(index + 1, start + 1, end, "\n".join(selected), clipped)


def match_page(items: Iterable[dict], offset: int, maximum: int) -> dict:
    matches: list[dict] = []
    total = 0
    size = 0
    stopped = False
    for item in items:
        total += 1
        if total <= offset:
            continue
        length = len(json.dumps(item, ensure_ascii=False))
        if stopped or len(matches) >= maximum or size + length > 10000:
            stopped = True
            continue
        matches.append(item)
        size += length
    next_offset = offset + len(matches)
    return {
        "matches": matches,
        "total_matches": total,
        "next_offset": next_offset if next_offset < total else None,
        "truncated": offset > 0
        or next_offset < total
        or any(item.get("excerpt_truncated") for item in matches),
    }
