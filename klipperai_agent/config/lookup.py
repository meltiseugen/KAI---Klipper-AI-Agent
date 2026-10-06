from __future__ import annotations

import re

from klipperai_agent.config.matching import _inline_code, _section_matches_prefix
from klipperai_agent.config.models import (
    ConfigRequestTarget,
    ConfigSectionLocation,
    ConfigSnapshot,
    _ConfigLineReference,
)
from klipperai_agent.config.vocabulary import _SECTION_LINE_PATTERN


def build_config_lookup_response(
    snapshot: ConfigSnapshot,
    target: ConfigRequestTarget,
    *,
    include_content: bool = False,
) -> tuple[str, list[str]]:
    matches = snapshot.find_section_locations(target)
    label = _describe_lookup_target(target)

    if matches:
        if _is_exact_macro_lookup(target):
            return _build_exact_macro_lookup_response(
                snapshot, target, matches, include_content=include_content
            )

        noun = "section" if len(matches) == 1 else "sections"
        lines = [
            f"I found {len(matches)} active {label} {noun} in the current config tree.",
            "",
            "Matches:",
        ]
        lines.extend(f"- {match.summary()}" for match in matches)
        next_actions: list[str] = []
        if len(matches) > 1:
            next_actions.append(
                "Ask for an exact section name if you want one match narrowed further."
            )
        elif include_content:
            block = snapshot.section_block(matches[0])
            if block:
                lines.extend(["", "Config:", "```ini", block, "```"])
        return "\n".join(lines), next_actions

    lines = [f"I couldn't find any active {label} sections in the current config tree."]
    next_actions = [
        "Ask for the exact section name if you know it, for example [extruder] or [fan_generic part_cooling].",
        "Check whether the section lives in an include path outside the collected config tree.",
    ]
    return "\n".join(lines), next_actions


def _is_exact_macro_lookup(target: ConfigRequestTarget) -> bool:
    return bool(target.section_name and _section_matches_prefix(target.section_name, "gcode_macro"))


def _build_exact_macro_lookup_response(
    snapshot: ConfigSnapshot,
    target: ConfigRequestTarget,
    matches: list[ConfigSectionLocation],
    *,
    include_content: bool,
) -> tuple[str, list[str]]:
    if len(matches) == 1:
        match = matches[0]
        macro_name = _macro_name_from_section(match.section) or _macro_name_from_section(
            target.section_name or ""
        )
        subject = macro_name or f"[{match.section}]"
        lines = [f"{subject} is defined in {match.path}:{match.line_number} as [{match.section}]."]
        if macro_name:
            references = _find_macro_references(snapshot, macro_name, definition=match)
            lines.extend(["", *_format_macro_reference_lines(macro_name, references)])

        block = snapshot.section_block(match)
        behavior_lines = _format_macro_behavior_lines(block)
        if behavior_lines:
            lines.extend(["", *behavior_lines])

        if include_content:
            if block:
                lines.extend(["", "Config:", "```ini", block, "```"])
        return "\n".join(lines), []

    lines = [
        f"I found {len(matches)} active definitions for {_describe_lookup_target(target)} in the current config tree.",
        "",
        "Matches:",
    ]
    lines.extend(f"- {match.summary()}" for match in matches)
    return "\n".join(lines), [
        "Remove or rename duplicate macro definitions so only one active section remains."
    ]


def _macro_name_from_section(section_name: str) -> str | None:
    parts = section_name.split(maxsplit=1)
    if len(parts) != 2 or parts[0].lower() != "gcode_macro":
        return None
    return parts[1].strip() or None


def _find_macro_references(
    snapshot: ConfigSnapshot,
    macro_name: str,
    *,
    definition: ConfigSectionLocation,
    limit: int = 8,
) -> list[_ConfigLineReference]:
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_-]){re.escape(macro_name)}(?![A-Za-z0-9_-])", re.IGNORECASE
    )
    references: list[_ConfigLineReference] = []

    for document in snapshot.documents:
        current_section: str | None = None
        for line_number, raw_line in enumerate(document.content.splitlines(), start=1):
            section_match = _SECTION_LINE_PATTERN.match(raw_line)
            if section_match:
                current_section = raw_line.strip()[1:-1].strip()
                continue

            if document.path == definition.path and current_section == definition.section:
                continue

            searchable_line = _strip_config_comments(raw_line).strip()
            if not searchable_line or not pattern.search(searchable_line):
                continue

            references.append(
                _ConfigLineReference(
                    path=document.path,
                    line_number=line_number,
                    section=current_section,
                    line_text=searchable_line,
                )
            )
            if len(references) >= limit:
                return references

    return references


def _format_macro_reference_lines(
    macro_name: str, references: list[_ConfigLineReference]
) -> list[str]:
    if not references:
        return [
            "Used by: no direct calls found in the collected config files.",
            "It may still be run manually, from the printer UI, or by slicer/start g-code outside this config tree.",
        ]

    lines = ["Used by:"]
    lines.extend(f"- {reference.summary()}" for reference in references)
    return lines


def _format_macro_behavior_lines(block: str | None) -> list[str]:
    if not block:
        return []

    description, commands = _extract_macro_behavior(block)
    lines: list[str] = []
    if description:
        lines.append(f"Description: {description}")

    summaries = [_summarize_macro_command(command) for command in commands[:5]]
    if not summaries:
        return lines

    lines.append("What it does:")
    lines.extend(f"- {summary}" for summary in summaries)
    if len(commands) > len(summaries):
        lines.append(f"- ...and {len(commands) - len(summaries)} more command(s).")
    return lines


def _extract_macro_behavior(block: str) -> tuple[str | None, list[str]]:
    description: str | None = None
    commands: list[str] = []
    in_gcode = False

    for raw_line in block.splitlines()[1:]:
        line_without_comment = _strip_config_comments(raw_line).rstrip()
        stripped = line_without_comment.strip()
        if not stripped:
            continue

        option_match = re.match(r"^([A-Za-z0-9_]+)\s*:\s*(.*?)\s*$", line_without_comment)
        if option_match:
            option = option_match.group(1).strip().lower()
            value = option_match.group(2).strip()
            in_gcode = option == "gcode"
            if option == "description" and value:
                description = value.strip("\"'")
            elif in_gcode and value:
                commands.append(value)
            continue

        if not in_gcode:
            continue

        if stripped.startswith(("{%", "{#", "{{")):
            continue
        commands.append(stripped)

    return description, commands


def _summarize_macro_command(command: str) -> str:
    compact_command = re.sub(r"\s+", " ", command).strip()
    command_name = compact_command.split(maxsplit=1)[0].upper() if compact_command else ""
    params = _parse_gcode_params(compact_command)

    if command_name == "SET_FILAMENT_SENSOR":
        sensor = params.get("SENSOR")
        enabled = params.get("ENABLE")
        if sensor and enabled == "1":
            return f"enables filament sensor `{_inline_code(sensor)}`."
        if sensor and enabled == "0":
            return f"disables filament sensor `{_inline_code(sensor)}`."
        if sensor:
            return f"updates filament sensor `{_inline_code(sensor)}`."

    return f"runs `{_inline_code(compact_command)}`."


def _parse_gcode_params(command: str) -> dict[str, str]:
    return {
        match.group(1).upper(): match.group(2).strip("\"'")
        for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)=(\"[^\"]*\"|'[^']*'|\S+)", command)
    }


def _strip_config_comments(line: str) -> str:
    return line.split("#", 1)[0].split(";", 1)[0]


def _describe_lookup_target(target: ConfigRequestTarget) -> str:
    if target.section_name:
        return f"[{target.section_name}]"
    labels = {
        "fan": "fan-related",
        "macro": "macro-related",
        "sensor": "sensor-related",
        "probe": "probe-related",
        "heater": "heater-related",
        "input_shaper": "input-shaper-related",
        "bed_mesh": "bed-mesh-related",
        "filament": "filament-sensor-related",
        "canbus": "CAN-related",
        "stepper": "stepper-related",
        "extruder": "extruder-related",
        "generic": "matching",
    }
    return labels.get(target.feature, "matching")
