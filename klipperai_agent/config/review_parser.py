"""Parse snippets without executing macros, resolving includes, or modifying files."""

from __future__ import annotations

import configparser
import re
from dataclasses import dataclass, field

from klipperai_agent.domain.proposals import ReviewCheck


@dataclass
class ReviewSection:
    name: str
    line: int
    values: dict[str, str] = field(default_factory=dict)
    lines: dict[str, int] = field(default_factory=dict)


def parse_review_config(content: str) -> tuple[list[ReviewSection], list[ReviewCheck]]:
    # Klipper strips '#' comments even without preceding whitespace.
    content = "\n".join(line.split("#", 1)[0] for line in content.splitlines())
    parser = configparser.RawConfigParser(
        strict=True, inline_comment_prefixes=("#", ";"), empty_lines_in_values=True
    )
    try:
        parser.read_string(content)
        if parser.defaults() or any(not name.strip() for name in parser.sections()):
            raise configparser.Error(
                "DEFAULT inheritance or empty section names require manual correction."
            )
    except configparser.Error as exc:
        return [], [
            ReviewCheck(
                code="config_syntax",
                severity="error",
                message="Config syntax is ambiguous or invalid; check duplicate options/sections, headers and indentation.",
                line=getattr(exc, "lineno", None),
            )
        ]
    sections = {
        name: ReviewSection(name.strip(), 1, dict(parser.items(name))) for name in parser.sections()
    }
    current: ReviewSection | None = None
    option_indent: int | None = None
    for number, raw in enumerate(content.splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        indent = len(raw) - len(raw.lstrip())
        if current is not None and option_indent is not None and indent > option_indent:
            continue
        header = re.match(r"^\[([^\]]+)\]", stripped)
        if header:
            current = sections.get(header.group(1))
            if current is not None:
                current.line = number
            option_indent = None
        elif current is not None:
            option = re.match(r"([^:=]+?)\s*[:=]", stripped)
            if option:
                current.lines[option.group(1).strip().lower()] = number
                option_indent = indent
    return [
        section for section in sections.values() if not section.name.lower().startswith("include ")
    ], []
