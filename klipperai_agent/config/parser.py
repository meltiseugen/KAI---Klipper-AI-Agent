from __future__ import annotations

import re

from klipperai_agent.config.models import (
    ConfigPlaceholder,
    ConfigSectionLocation,
)


class ConfigParser:
    _INCLUDE_PATTERN = re.compile(r"^\s*\[include\s+([^\]]+)\]\s*$", re.IGNORECASE | re.MULTILINE)

    _SECTION_PATTERN = re.compile(r"^\s*\[([^\]]+)\]\s*$", re.MULTILINE)

    _OPTION_PATTERN = re.compile(r"^\s*([A-Za-z0-9_]+)\s*:\s*(.+?)\s*$")

    _PLACEHOLDER_VALUE_PATTERN = re.compile(r"^(YOUR_[A-Z0-9_]+|<[A-Z0-9_]+>)$")

    @classmethod
    def extract_include_patterns(cls, content: str) -> list[str]:
        return [
            match.group(1).strip().strip("\"'") for match in cls._INCLUDE_PATTERN.finditer(content)
        ]

    @classmethod
    def extract_sections(cls, content: str) -> list[str]:
        sections: list[str] = []
        for match in cls._SECTION_PATTERN.finditer(content):
            section = match.group(1).strip()
            if section.lower().startswith("include "):
                continue
            sections.append(section)
        return sections

    @classmethod
    def extract_section_locations(cls, path: str, content: str) -> list[ConfigSectionLocation]:
        locations: list[ConfigSectionLocation] = []

        for line_number, raw_line in enumerate(content.splitlines(), start=1):
            section_match = cls._SECTION_PATTERN.match(raw_line)
            if not section_match:
                continue

            section = section_match.group(1).strip()
            if section.lower().startswith("include "):
                continue

            locations.append(
                ConfigSectionLocation(
                    path=path,
                    line_number=line_number,
                    section=section,
                )
            )

        return locations

    @classmethod
    def detect_placeholders(cls, path: str, content: str) -> list[ConfigPlaceholder]:
        placeholders: list[ConfigPlaceholder] = []
        current_section: str | None = None

        for line_number, raw_line in enumerate(content.splitlines(), start=1):
            section_match = cls._SECTION_PATTERN.match(raw_line)
            if section_match:
                section = section_match.group(1).strip()
                if not section.lower().startswith("include "):
                    current_section = section
                continue

            normalized_line = raw_line.split("#", 1)[0].strip()
            if not normalized_line:
                continue

            option_match = cls._OPTION_PATTERN.match(normalized_line)
            if not option_match:
                continue

            option = option_match.group(1).strip()
            value = option_match.group(2).strip()
            unquoted_value = value.strip("\"'")
            if not cls._PLACEHOLDER_VALUE_PATTERN.fullmatch(unquoted_value):
                continue

            placeholders.append(
                ConfigPlaceholder(
                    path=path,
                    line_number=line_number,
                    line_text=normalized_line,
                    value=unquoted_value,
                    section=current_section,
                    option=option,
                )
            )

        return placeholders
