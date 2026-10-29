"""Evidence-based feature drafts with explicit, bounded user-supplied parameters."""

from __future__ import annotations

import re

from klipperai_agent.config.models import ConfigDocument
from klipperai_agent.config.requests import ConfigPromptPayload
from klipperai_agent.config.review_parser import ReviewSection, parse_review_config
from klipperai_agent.domain.proposals import ConfigProposal

FEATURE_OPTIONS = {
    "input_shaper": (
        "shaper_type",
        "shaper_type_x",
        "shaper_type_y",
        "shaper_freq_x",
        "shaper_freq_y",
        "damping_ratio_x",
        "damping_ratio_y",
    ),
    "bed_mesh": (
        "speed",
        "horizontal_move_z",
        "mesh_min",
        "mesh_max",
        "probe_count",
        "algorithm",
        "mesh_pps",
        "bicubic_tension",
        "fade_start",
        "fade_end",
        "fade_target",
    ),
    "probe": (
        "pin",
        "x_offset",
        "y_offset",
        "z_offset",
        "speed",
        "lift_speed",
        "samples",
        "sample_retract_dist",
        "samples_result",
        "samples_tolerance",
        "samples_tolerance_retries",
    ),
}


def feature_proposal(payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal | None:
    feature = payload.target.feature
    if feature == "macro" and re.search(r"\b(status|diagnostic)\b", payload.user_message, re.I):
        return ConfigProposal(
            feature="macro",
            title="Printer status report macro",
            target_file="klipperai/macros.cfg",
            config=(
                "[gcode_macro KLIPPERAI_STATUS]\n"
                "description: Report current printer status without moving or heating\n"
                "gcode:\n"
                '  {action_respond_info("Printer: %s; homed axes: %s" % (printer.webhooks.state, printer.toolhead.homed_axes))}\n'
                '  {% if "extruder" in printer %}\n'
                '    {action_respond_info("Extruder: %.1f / %.1f C" % (printer.extruder.temperature, printer.extruder.target))}\n'
                "  {% endif %}\n"
                '  {% if "heater_bed" in printer %}\n'
                '    {action_respond_info("Bed: %.1f / %.1f C" % (printer.heater_bed.temperature, printer.heater_bed.target))}\n'
                "  {% endif %}\n"
            ),
            rationale="A functional status macro using Klipper's printer status objects and action_respond_info; no RESPOND dependency, movement or heater commands.",
            assumptions=["Verify template/status-object support against the installed firmware."],
            warnings=warnings,
        )
    if feature not in FEATURE_OPTIONS:
        return None
    requested: dict[str, str] = {}
    for option in FEATURE_OPTIONS[feature]:
        value_pattern = (
            r"[^\s;,]+(?:\s*,\s*[^\s;,]+)?"
            if option in {"mesh_min", "mesh_max", "probe_count", "mesh_pps"}
            else r"[^\s;,]+"
        )
        match = re.search(rf"\b{option}\s*[:=]\s*({value_pattern})", payload.user_message, re.I)
        if match:
            requested[option] = match[1]
    matches: list[tuple[ConfigDocument, ReviewSection]] = []
    for doc in payload.snapshot.documents:
        parsed, errors = parse_review_config(doc.content)
        if not errors and not doc.truncated:
            matches.extend((doc, section) for section in parsed if section.name == feature)
    if not requested:
        return None
    if len(matches) > 1:
        warnings.append(
            "Multiple feature sections were observed; resolve overrides before generating a consolidated draft."
        )
        return None
    values: dict[str, str] = {}
    target = f"klipperai/{feature}.cfg"
    assumptions = [
        "Requested values are user-supplied, not independently measured or hardware-verified."
    ]
    if matches:
        doc, section = matches[0]
        target = doc.path
        values.update(section.values)
        assumptions.append(
            f"Retain observed options from [{feature}] in {doc.path}:{section.line}."
        )
    values.update(requested)
    required = {
        "input_shaper": {"shaper_freq_x": "<X_FREQ>", "shaper_freq_y": "<Y_FREQ>"},
        "bed_mesh": {"mesh_min": "<MIN_X>,<MIN_Y>", "mesh_max": "<MAX_X>,<MAX_Y>"},
        "probe": {"pin": "<PROBE_PIN>", "z_offset": "<Z_OFFSET>"},
    }[feature]
    for option, placeholder in required.items():
        values.setdefault(option, placeholder)
    if feature == "input_shaper" and "shaper_type" not in values:
        values.setdefault("shaper_type_x", "<X_SHAPER_TYPE>")
        values.setdefault("shaper_type_y", "<Y_SHAPER_TYPE>")
    snippet = (
        f"[{feature}]\n"
        + "\n".join(f"{key}: " + value.replace("\n", "\n  ") for key, value in values.items())
        + "\n"
    )
    return ConfigProposal(
        feature=feature,
        title=f"Configured {feature.replace('_', ' ')} draft",
        target_file=target,
        config=snippet,
        rationale="Merge explicit feature parameters with observed options. Unknown calibration, bounds and hardware remain placeholders.",
        assumptions=assumptions,
        warnings=[
            *warnings,
            "Verify probe travel and offsets, mesh bounds, or resonance measurements as appropriate before manually editing. No calibration has been performed.",
        ],
    )
