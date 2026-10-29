"""Useful manual drafts with no invented geometry, pins or resonance measurements."""

import re

from klipperai_agent.config.requests import ConfigPromptPayload
from klipperai_agent.config.review_parser import parse_review_config
from klipperai_agent.domain.proposals import ConfigProposal


def _parameter(message: str, option: str, fallback: str) -> str:
    value = (
        r"[^\s;,]+(?:\s*,\s*[^\s;,]+){0,2}"
        if option in {"axes_map", "probe_points"}
        else r"[^\s;]+"
    )
    found = re.search(rf"\b{re.escape(option)}\s*[:=]\s*({value})", message, re.I)
    return found[1] if found else fallback


def _draft(
    payload: ConfigPromptPayload, section: str, feature: str, body: str, warnings: list[str]
) -> ConfigProposal:
    target = f"klipperai/{feature}.cfg"
    locations: list[tuple[str, int]] = []
    for document in payload.snapshot.documents:
        parsed, errors = parse_review_config(document.content)
        if not errors and not document.truncated:
            locations.extend(
                (document.path, item.line)
                for item in parsed
                if item.name.casefold() == section.casefold()
            )
    if len(locations) == 1:
        target = locations[0][0]
    return ConfigProposal(
        feature=payload.target.feature,
        title=f"{section} manual draft",
        target_file=target,
        config=f"[{section}]\n{body}\n",
        rationale="Purpose-specific template; inspect the proposed comparison and manual file patch before editing.",
        assumptions=[
            "Installed firmware support, physical wiring and calibration remain unverified.",
            "Review any existing macro body and printer-specific start/end sequence before replacement.",
        ],
        warnings=[
            *warnings,
            "This is a manual draft. No printer command, calibration or measurement has been performed.",
            *(
                ["Multiple target sections exist; reconcile overrides before using this draft."]
                if len(locations) > 1
                else []
            ),
        ],
    )


def advanced_proposal(payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal | None:
    message = payload.user_message
    if payload.target.feature == "macro":
        if re.search(r"\b(?:start[_ ]print|print[_ ]start)\b", message, re.I):
            return _draft(
                payload,
                "gcode_macro START_PRINT",
                "macros",
                """description: Require explicit slicer temperatures, home, and wait for temperature
gcode:
  {% set bed = params.BED_TEMP|default(0)|float %}
  {% set hotend = params.EXTRUDER_TEMP|default(0)|float %}
  {% if printer.webhooks.state != 'ready' %}
    {action_raise_error('Printer is not ready')}
  {% endif %}
  {% if bed <= 0 or hotend <= 0 %}
    {action_raise_error('Pass BED_TEMP and EXTRUDER_TEMP from the slicer')}
  {% endif %}
  M140 S{bed}
  M104 S{hotend}
  G28
  M190 S{bed}
  M109 S{hotend}""",
                [
                    *warnings,
                    "Requires extruder and heater_bed. Verify homing clearance, material temperatures and the printer's leveling/probe sequence manually. This template does not invent purge moves or load a mesh.",
                ],
            )
        if re.search(r"\b(?:end[_ ]print|print[_ ]end)\b", message, re.I):
            return _draft(
                payload,
                "gcode_macro END_PRINT",
                "macros",
                """description: Finish queued moves and turn off heaters without parking or retracting
gcode:
  M400
  TURN_OFF_HEATERS
  {% if 'fan' in printer %}
    M107
  {% endif %}""",
                [
                    *warnings,
                    "No parking, retract or motor-disable behavior is assumed; add only verified printer-specific steps manually.",
                ],
            )
        if re.search(r"\b(preflight|ready check)\b", message, re.I):
            return _draft(
                payload,
                "gcode_macro KLIPPERAI_PREFLIGHT",
                "macros",
                """description: Report ready and homing state without moving or heating
gcode:
  {% if printer.webhooks.state != 'ready' %}
    {action_raise_error('Printer is not ready')}
  {% endif %}
  {action_respond_info('Homed axes: %s' % printer.toolhead.homed_axes)}""",
                warnings,
            )
    if payload.target.feature == "probe" and re.search(r"\bbltouch\b", message, re.I):
        defaults = {
            "sensor_pin": "<SENSOR_PIN>",
            "control_pin": "<CONTROL_PIN>",
            "x_offset": "<X_OFFSET>",
            "y_offset": "<Y_OFFSET>",
            "z_offset": "<Z_OFFSET>",
        }
        values = dict(defaults)
        for document in payload.snapshot.documents:
            parsed, errors = parse_review_config(document.content)
            if not errors and not document.truncated:
                for section in parsed:
                    if section.name == "bltouch":
                        values.update(section.values)
        for key, fallback in list(values.items()):
            values[key] = _parameter(message, key, fallback)
        return _draft(
            payload,
            "bltouch",
            "probe",
            "\n".join(f"{key}: {value}" for key, value in values.items()),
            [
                *warnings,
                "Confirm BLTouch-compatible hardware, sensor/control wiring, offsets and firmware support; no generic probe section is added.",
            ],
        )
    if payload.target.feature == "input_shaper" and re.search(
        r"\b(resonance tester|accelerometer|adxl345|lis2dw)\b", message, re.I
    ):
        sensor = "lis2dw" if re.search(r"\blis2dw\b", message, re.I) else "adxl345"
        chip = _parameter(message, "cs_pin", "<CS_PIN>")
        axes = _parameter(message, "axes_map", "<AXES_MAP>")
        point = _parameter(message, "probe_points", "<SAFE_X>,<SAFE_Y>,<SAFE_Z>")
        body = f"cs_pin: {chip}\naxes_map: {axes}\n"
        bus = _parameter(message, "spi_bus", "")
        if bus:
            body += f"spi_bus: {bus}\n"
        body += f"\n[resonance_tester]\naccel_chip: {sensor}\nprobe_points:\n  {point}"
        return _draft(
            payload,
            sensor,
            "input_shaper",
            body,
            [
                *warnings,
                "Verify sensor type, bus pins, axes orientation, mounting and safe measurement coordinates. No test motion or shaper-frequency recommendation is generated.",
            ],
        )
    return None
