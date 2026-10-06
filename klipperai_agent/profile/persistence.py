from __future__ import annotations

import configparser
import re
from pathlib import Path

from klipperai_agent.profile.models import PrinterProfile

_INI_SECTION_PATTERN = re.compile(r"^\s*\[([^\]]+)\]\s*$")


_INI_OPTION_PATTERN = re.compile(r"^(\s*)([A-Za-z0-9_.-]+)(\s*[:=]\s*)(.*?)(\s+(?:#|;).*)?\s*$")


def write_profile_to_cfg(
    config_file: Path,
    profile: PrinterProfile,
    *,
    root_config_file: str | None = None,
    overwrite: bool = False,
) -> None:
    parser = configparser.ConfigParser(
        interpolation=None,
        inline_comment_prefixes=("#", ";"),
    )
    parser.read(config_file, encoding="utf-8")

    section_values = {
        "printer_identity": {
            "firmware_flavor": profile.firmware_flavor or "",
            "firmware_version": profile.firmware_version or "",
            "host_model": profile.host_model or "",
            "host_distribution": profile.host_distribution or "",
            "mainboard": profile.mainboard or "",
            "toolhead": profile.toolhead_board or profile.toolhead or "",
        },
        "printer_capabilities": {
            "probe_type": profile.probe_type or "",
            "accelerometer": profile.accelerometer or "",
            "filament_sensor": profile.filament_sensor or "",
            "bed_mesh_configured": "true" if profile.bed_mesh_configured else "false",
            "input_shaper_configured": "true" if profile.input_shaper_configured else "false",
            "canbus_enabled": "true" if profile.canbus_enabled else "false",
            "addons": ", ".join(sorted(addon.name for addon in profile.addons)),
        },
        "config_context": {
            "root_config_file": root_config_file or "",
        },
    }

    parser.remove_section("printer_geometry")
    if parser.has_section("printer_identity"):
        parser.remove_option("printer_identity", "mainboard_mcu")
        parser.remove_option("printer_identity", "toolhead_board")
    if parser.has_section("printer_capabilities"):
        parser.remove_option("printer_capabilities", "camera_stack")

    for section, values in section_values.items():
        if not parser.has_section(section):
            parser.add_section(section)
        for key, value in values.items():
            if overwrite:
                parser.set(section, key, value)
                continue
            existing = parser.get(section, key, fallback="").strip()
            if existing and not _should_replace_profile_value(section, key, existing, value):
                continue
            parser.set(section, key, value)

    persisted_values = {
        section: {key: parser.get(section, key, fallback="") for key in values}
        for section, values in section_values.items()
        if parser.has_section(section)
    }
    _rewrite_cfg_preserving_comments(
        config_file,
        section_values=persisted_values,
        removed_sections={"printer_geometry"},
        removed_options={
            "printer_identity": {"mainboard_mcu", "toolhead_board"},
            "printer_capabilities": {"camera_stack"},
        },
    )


def _should_replace_profile_value(section: str, key: str, existing: str, value: str) -> bool:
    if (
        section == "printer_capabilities"
        and key in {"bed_mesh_configured", "input_shaper_configured", "canbus_enabled"}
        and existing.strip().lower() == "false"
        and value.strip().lower() == "true"
    ):
        return True
    return False


def _rewrite_cfg_preserving_comments(
    config_file: Path,
    *,
    section_values: dict[str, dict[str, str]],
    removed_sections: set[str],
    removed_options: dict[str, set[str]],
) -> None:
    original_text = config_file.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in original_text else "\n"
    lines = original_text.splitlines(keepends=True)

    prefix, section_blocks = _split_ini_blocks(lines)
    seen_sections: set[str] = set()
    rewritten_blocks: list[str] = []

    for section_name, block_lines in section_blocks:
        normalized = section_name.strip().lower()
        if normalized in removed_sections:
            continue
        seen_sections.add(normalized)
        rewritten_blocks.append(
            _rewrite_ini_section_block(
                block_lines,
                values=section_values.get(normalized, {}),
                removed_option_names=removed_options.get(normalized, set()),
                newline=newline,
            )
        )

    for section_name, values in section_values.items():
        if section_name in seen_sections:
            continue
        rewritten_blocks.append(
            _build_ini_section_block(
                section_name,
                values=values,
                newline=newline,
            )
        )

    rewritten_text = "".join(prefix) + "".join(rewritten_blocks)
    if (
        original_text.endswith(("\n", "\r"))
        and rewritten_text
        and not rewritten_text.endswith(("\n", "\r"))
    ):
        rewritten_text += newline
    config_file.write_text(rewritten_text, encoding="utf-8")


def _split_ini_blocks(lines: list[str]) -> tuple[list[str], list[tuple[str, list[str]]]]:
    prefix: list[str] = []
    blocks: list[tuple[str, list[str]]] = []
    current_name: str | None = None
    current_block: list[str] = []

    for line in lines:
        match = _INI_SECTION_PATTERN.match(line)
        if match:
            if current_name is None:
                if current_block:
                    prefix.extend(current_block)
            else:
                blocks.append((current_name, current_block))
            current_name = match.group(1)
            current_block = [line]
            continue
        current_block.append(line)

    if current_name is None:
        prefix.extend(current_block)
    else:
        blocks.append((current_name, current_block))
    return prefix, blocks


def _rewrite_ini_section_block(
    block_lines: list[str],
    *,
    values: dict[str, str],
    removed_option_names: set[str],
    newline: str,
) -> str:
    if not block_lines:
        return ""

    rewritten: list[str] = [block_lines[0]]
    seen_keys: set[str] = set()

    for line in block_lines[1:]:
        option_match = _INI_OPTION_PATTERN.match(line)
        if not option_match:
            rewritten.append(line)
            continue

        leading = option_match.group(1)
        raw_key = option_match.group(2)
        separator = option_match.group(3)
        key = raw_key.strip().lower()
        remainder = option_match.group(4) or ""
        suffix = option_match.group(5) or ""
        comment = suffix.lstrip()
        if not comment and remainder.lstrip().startswith(("#", ";")):
            comment = remainder.lstrip()
        if key in removed_option_names:
            continue
        if key in values:
            if key in seen_keys:
                continue
            rewritten.append(
                _format_ini_option_line(
                    leading=leading,
                    raw_key=raw_key,
                    separator=separator,
                    value=values[key],
                    comment=comment,
                    newline=newline,
                )
            )
            seen_keys.add(key)
            continue
        rewritten.append(line)

    trailing_blanks: list[str] = []
    while rewritten[1:] and rewritten[-1].strip() == "":
        trailing_blanks.append(rewritten.pop())
    trailing_blanks.reverse()

    for key, value in values.items():
        if key in seen_keys:
            continue
        rewritten.append(f"{key}: {value}{newline}")

    rewritten.extend(trailing_blanks)
    return "".join(rewritten)


def _format_ini_option_line(
    *,
    leading: str,
    raw_key: str,
    separator: str,
    value: str,
    comment: str,
    newline: str,
) -> str:
    normalized_separator = separator.rstrip()
    if comment:
        if value:
            return f"{leading}{raw_key}{normalized_separator} {value}  {comment}{newline}"
        return f"{leading}{raw_key}{normalized_separator}  {comment}{newline}"
    return f"{leading}{raw_key}{normalized_separator} {value}{newline}"


def _build_ini_section_block(
    section_name: str,
    *,
    values: dict[str, str],
    newline: str,
) -> str:
    lines = [f"[{section_name}]{newline}"]
    for key, value in values.items():
        lines.append(f"{key}: {value}{newline}")
    lines.append(newline)
    return "".join(lines)
