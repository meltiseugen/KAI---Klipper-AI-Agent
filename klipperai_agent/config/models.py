from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from klipperai_agent.config.matching import (
    _inline_code,
    _normalize_section_lookup_key,
    _section_matches_prefix,
)
from klipperai_agent.config.vocabulary import (
    _FEATURE_SECTION_PREFIXES,
    _SECTION_LINE_PATTERN,
    ConfigFeature,
    ConfigRequestIntent,
)


@dataclass(slots=True)
class ConfigDocument:
    path: str
    content: str
    sections: list[str]
    content_digest: str = ""
    truncated: bool = False

    def prompt_block(self) -> str:
        section_text = ", ".join(self.sections[:12]) if self.sections else "no sections detected"
        return f"File: {self.path}\nSections: {section_text}\n\n{self.content}"


@dataclass(frozen=True, slots=True)
class ConfigPlaceholder:
    path: str
    line_number: int
    line_text: str
    value: str
    section: str | None = None
    option: str | None = None

    def summary(self) -> str:
        details: list[str] = [f"{self.value} at {self.path}:{self.line_number}"]
        if self.section:
            details.append(f"section [{self.section}]")
        if self.option:
            details.append(f"option {self.option}")
        return " | ".join(details)


@dataclass(frozen=True, slots=True)
class ConfigSectionLocation:
    path: str
    line_number: int
    section: str

    def summary(self) -> str:
        return f"[{self.section}] at {self.path}:{self.line_number}"


@dataclass(frozen=True, slots=True)
class _ConfigLineReference:
    path: str
    line_number: int
    section: str | None
    line_text: str

    def summary(self) -> str:
        location = f"{self.path}:{self.line_number}"
        section = f"[{self.section}]" if self.section else "top level"
        return f"{section} at {location}: `{_inline_code(self.line_text)}`"


@dataclass(slots=True)
class ConfigSnapshot:
    root_file: str | None
    documents: list[ConfigDocument]
    section_locations: list[ConfigSectionLocation] = field(default_factory=list)
    placeholders: list[ConfigPlaceholder] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def revision(self) -> str:
        files = [
            (item.path, item.content_digest or hashlib.sha256(item.content.encode()).hexdigest())
            for item in sorted(self.documents, key=lambda item: item.path)
        ]
        return hashlib.sha256(
            json.dumps([self.root_file, files, self.notes], sort_keys=True).encode()
        ).hexdigest()

    @property
    def section_names(self) -> list[str]:
        names: list[str] = []
        for document in self.documents:
            names.extend(document.sections)
        return names

    def has_section_prefix(self, prefix: str) -> bool:
        prefix_lower = prefix.lower()
        return any(section.lower().startswith(prefix_lower) for section in self.section_names)

    def has_managed_include(self, include_name: str = "klipperai") -> bool:
        include_pattern = re.compile(
            rf"^\s*\[include\s+.*{re.escape(include_name)}.*\]\s*$",
            re.IGNORECASE | re.MULTILINE,
        )
        return any(include_pattern.search(document.content) for document in self.documents)

    def find_section_locations(
        self,
        target: "ConfigRequestTarget",
        *,
        limit: int = 12,
    ) -> list[ConfigSectionLocation]:
        if target.section_name:
            requested_key = _normalize_section_lookup_key(target.section_name)
            matches = [
                location
                for location in self.section_locations
                if location.section.lower() == target.section_name.lower()
                or _normalize_section_lookup_key(location.section) == requested_key
            ]
            return matches[:limit]

        prefixes = _FEATURE_SECTION_PREFIXES.get(target.feature, ())
        matches = [
            location
            for location in self.section_locations
            if any(_section_matches_prefix(location.section, prefix) for prefix in prefixes)
        ]
        return matches[:limit]

    def section_block(self, location: ConfigSectionLocation) -> str | None:
        document = next((item for item in self.documents if item.path == location.path), None)
        if document is None:
            return None

        lines = document.content.splitlines()
        start_index = max(location.line_number - 1, 0)
        if start_index >= len(lines):
            return None

        end_index = len(lines)
        for index in range(start_index + 1, len(lines)):
            if _SECTION_LINE_PATTERN.match(lines[index]):
                end_index = index
                break

        block = "\n".join(lines[start_index:end_index]).rstrip()
        return block or None

    def to_prompt_block(self, max_documents: int | None = None) -> str:
        sections: list[str] = []
        if self.root_file:
            sections.append(f"Root config: {self.root_file}")
        sections.append("Config paths below are relative to the Klipper config directory.")
        if self.notes:
            sections.append("Collector notes:\n" + "\n".join(self.notes))
        if self.placeholders:
            placeholder_lines = [
                f"- {placeholder.summary()}" for placeholder in self.placeholders[:6]
            ]
            sections.append("Detected placeholder values:\n" + "\n".join(placeholder_lines))
        if self.documents:
            documents = self.documents if max_documents is None else self.documents[:max_documents]
            document_blocks = [document.prompt_block() for document in documents]
            sections.append("Config files:\n" + "\n\n".join(document_blocks))
        else:
            sections.append("No config files were collected.")
        return "\n\n".join(sections)

    def to_state(self) -> dict[str, Any]:
        return {
            "root_file": self.root_file,
            "notes": list(self.notes),
            "section_locations": [
                {
                    "path": location.path,
                    "line_number": location.line_number,
                    "section": location.section,
                }
                for location in self.section_locations
            ],
            "placeholders": [
                {
                    "path": placeholder.path,
                    "line_number": placeholder.line_number,
                    "line_text": placeholder.line_text,
                    "value": placeholder.value,
                    "section": placeholder.section,
                    "option": placeholder.option,
                }
                for placeholder in self.placeholders
            ],
            "documents": [
                {
                    "path": document.path,
                    "content": document.content,
                    "sections": list(document.sections),
                    "content_digest": document.content_digest,
                    "truncated": document.truncated,
                }
                for document in self.documents
            ],
        }

    @classmethod
    def from_state(cls, data: dict[str, Any]) -> ConfigSnapshot:
        documents = [
            ConfigDocument(
                path=str(item.get("path", "")),
                content=str(item.get("content", "")),
                sections=[str(section) for section in item.get("sections", [])],
                content_digest=str(item.get("content_digest", "")),
                truncated=bool(item.get("truncated", False)),
            )
            for item in data.get("documents", [])
        ]
        section_locations = [
            ConfigSectionLocation(
                path=str(item.get("path", "")),
                line_number=int(item.get("line_number", 0)),
                section=str(item.get("section", "")),
            )
            for item in data.get("section_locations", [])
        ]
        placeholders = [
            ConfigPlaceholder(
                path=str(item.get("path", "")),
                line_number=int(item.get("line_number", 0)),
                line_text=str(item.get("line_text", "")),
                value=str(item.get("value", "")),
                section=str(item["section"]) if item.get("section") else None,
                option=str(item["option"]) if item.get("option") else None,
            )
            for item in data.get("placeholders", [])
        ]
        root_file = data.get("root_file")
        return cls(
            root_file=str(root_file) if root_file else None,
            documents=documents,
            section_locations=section_locations,
            placeholders=placeholders,
            notes=[str(note) for note in data.get("notes", [])],
        )


@dataclass(frozen=True, slots=True)
class ConfigRequestTarget:
    feature: ConfigFeature
    rationale: str
    intent: ConfigRequestIntent = "generate"
    section_name: str | None = None
