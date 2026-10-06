from __future__ import annotations

import re
from typing import Any, cast

from klipperai_agent.config.models import ConfigRequestTarget, ConfigSnapshot
from klipperai_agent.config.targeting import infer_config_request_target
from klipperai_agent.config.vocabulary import ConfigFeature, ConfigRequestIntent
from klipperai_agent.workflows.context import ConfigState
from klipperai_agent.workflows.text import _dedupe_items, _looks_like_macro_target

_CONFIG_SOURCE_EXCERPT_LIMIT = 12000


_BRACKETED_CONFIG_SECTION_PATTERN = re.compile(r"\[([^\]\n]{2,160})\]")


_BACKTICK_CONFIG_TOKEN_PATTERN = re.compile(r"`([^`\n]{2,160})`")


_UPPERCASE_CONFIG_TOKEN_PATTERN = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")


_KNOWN_CONFIG_SECTION_PREFIXES = (
    "gcode_macro",
    "delayed_gcode",
    "filament_switch_sensor",
    "filament_motion_sensor",
    "fan",
    "fan_generic",
    "heater_fan",
    "controller_fan",
    "temperature_fan",
    "temperature_sensor",
    "thermistor",
    "adc_temperature",
    "probe",
    "bltouch",
    "beacon",
    "cartographer",
    "probe_eddy_current",
    "input_shaper",
    "resonance_tester",
    "adxl345",
    "lis2dw",
    "bed_mesh",
    "mcu",
    "stepper_",
    "tmc",
    "extruder",
    "extruder_stepper",
    "heater_bed",
)


def _build_config_source_citations(
    state: ConfigState,
    *,
    response_text: str = "",
    limit: int = 8,
) -> list[dict[str, Any]]:
    snapshot = ConfigSnapshot.from_state(state.get("config_snapshot", {}))
    if not snapshot.section_locations:
        return []

    locations: list[Any] = []
    seen_locations: set[tuple[str, int, str]] = set()

    def add_locations(candidates: list[Any]) -> None:
        for location in candidates:
            key = (location.path, location.line_number, location.section.lower())
            if key in seen_locations:
                continue
            seen_locations.add(key)
            locations.append(location)
            if len(locations) >= limit:
                return

    target = _config_source_target_from_state(state)
    if target is not None:
        add_locations(snapshot.find_section_locations(target, limit=limit))

    for section_name in _extract_config_section_references(response_text):
        add_locations(_find_exact_source_locations(snapshot, section_name, limit=2))
        if len(locations) >= limit:
            break

    if len(locations) < limit:
        for macro_name in _extract_macro_references(response_text):
            add_locations(
                _find_exact_source_locations(snapshot, f"gcode_macro {macro_name}", limit=1)
            )
            if len(locations) >= limit:
                break

    citations: list[dict[str, Any]] = []
    for location in locations[:limit]:
        excerpt = snapshot.section_block(location) or ""
        citations.append(
            {
                "label": _format_source_citation_label(
                    location.path, location.line_number, location.section
                ),
                "path": location.path,
                "line_number": location.line_number if location.line_number > 0 else None,
                "section": location.section,
                "excerpt": _truncate_source_excerpt(excerpt),
            }
        )
    return citations


def _config_source_target_from_state(state: ConfigState) -> ConfigRequestTarget | None:
    detected = infer_config_request_target(state.get("user_message", ""))
    target_data = state.get("feature_target", {})
    feature = str(target_data.get("feature") or detected.feature or "generic")
    intent = str(target_data.get("intent") or detected.intent or "locate")
    section_name = (
        str(target_data.get("section_name") or detected.section_name or "").strip() or None
    )
    if feature == "generic" and not section_name:
        return None
    return ConfigRequestTarget(
        feature=cast(ConfigFeature, feature),
        rationale=str(
            target_data.get("rationale") or detected.rationale or "Response source target."
        ),
        intent=cast(ConfigRequestIntent, intent),
        section_name=section_name,
    )


def _find_exact_source_locations(
    snapshot: ConfigSnapshot,
    section_name: str,
    *,
    limit: int,
) -> list[Any]:
    normalized = section_name.strip().strip("[]")
    if not normalized:
        return []
    target = ConfigRequestTarget(
        feature="generic",
        rationale="Matched section reference in response.",
        intent="locate",
        section_name=normalized,
    )
    return snapshot.find_section_locations(target, limit=limit)


def _extract_config_section_references(text: str) -> list[str]:
    sections: list[str] = []
    for pattern in (_BRACKETED_CONFIG_SECTION_PATTERN, _BACKTICK_CONFIG_TOKEN_PATTERN):
        for match in pattern.finditer(text):
            candidate = match.group(1).strip()
            if _looks_like_config_section_reference(candidate):
                sections.append(candidate)
    return _dedupe_items(sections, limit=24)


def _extract_macro_references(text: str) -> list[str]:
    macros: list[str] = []
    for match in _UPPERCASE_CONFIG_TOKEN_PATTERN.finditer(text):
        candidate = match.group(0).strip()
        if _looks_like_macro_target(candidate):
            macros.append(candidate)
    return _dedupe_items(macros, limit=24)


def _looks_like_config_section_reference(candidate: str) -> bool:
    normalized = candidate.strip().strip("[]")
    lowered = normalized.lower()
    if not normalized or "/" in normalized or "\\" in normalized or lowered.endswith(".cfg"):
        return False
    return any(
        lowered == prefix or lowered.startswith(f"{prefix} ")
        for prefix in _KNOWN_CONFIG_SECTION_PREFIXES
    )


def _format_source_citation_label(path: str, line_number: int, section: str) -> str:
    if line_number > 0:
        return f"{path}:{line_number} [{section}]"
    return f"{path} [{section}]"


def _truncate_source_excerpt(excerpt: str) -> str:
    if len(excerpt) <= _CONFIG_SOURCE_EXCERPT_LIMIT:
        return excerpt
    return f"{excerpt[:_CONFIG_SOURCE_EXCERPT_LIMIT].rstrip()}\n...[truncated]..."
