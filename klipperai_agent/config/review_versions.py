"""Version-sensitive checks use exact known tags, never order arbitrary git hashes."""

from __future__ import annotations

import re
from typing import Literal

from klipperai_agent.config.option_rules import CHANGES, KALICO
from klipperai_agent.config.review_parser import ReviewSection
from klipperai_agent.domain.proposals import ReviewCheck, ReviewFirmware

# Verified against the tagged upstream docs/code, not inferred from current docs.
VERSIONED_OPTIONS = {
    ("printer", "minimum_cruise_ratio"): ("added", "minimum_cruise_ratio", "0.13.0"),
    ("printer", "max_accel_to_decel"): ("deprecated", "minimum_cruise_ratio", "0.13.0"),
    ("bed_mesh", "relative_reference_index"): ("removed", "zero_reference_position", "0.13.0"),
    ("output_pin", "static_value"): ("removed", "value and shutdown_value", "0.13.0"),
    ("output_pin", "maximum_mcu_duration"): ("removed", "a pwm_tool section", "0.13.0"),
}


def exact_klipper_release(firmware: ReviewFirmware) -> str | None:
    match = re.fullmatch(r"v?(0\.12\.0|0\.13\.0)(?:-0-g[0-9a-f]+)?", firmware.version)
    return match.group(1) if match and firmware.flavor.casefold() == "klipper" else None


def version_checks(
    section: ReviewSection, family: str, firmware: ReviewFirmware
) -> list[ReviewCheck]:
    checks = []
    release = exact_klipper_release(firmware)
    for option, value in section.values.items():
        rule = VERSIONED_OPTIONS.get((family, option))
        if rule:
            action, replacement, boundary = rule
            severity: Literal["error", "warning", "info"] = "warning"
            if release is None:
                message = f"{option} changed in upstream Klipper. Verify this exact fork/commit; migration reference: {replacement}."
            elif action == "added" and release != boundary:
                severity = "error"
                message = f"{option} is not supported by upstream Klipper {release}; it is present in {boundary}."
            elif action == "removed" and release == boundary:
                severity = "error"
                message = f"{option} was removed by upstream Klipper {boundary}; review migration to {replacement}."
            elif action == "deprecated" and release == boundary:
                message = f"{option} is deprecated in upstream Klipper {boundary}; review {replacement}. Later commits remove it."
            else:
                continue
            checks.append(
                ReviewCheck(
                    code="option_version",
                    severity=severity,
                    message=message,
                    section=section.name,
                    option=option,
                    line=section.lines.get(option, section.line),
                    source_url=CHANGES,
                )
            )
        if (
            family in {"heater_bed", "heater_generic", "extruder"}
            and option == "control"
            and value in {"mpc", "pid_v", "dual_loop_pid"}
        ):
            checks.append(
                ReviewCheck(
                    code="fork_control",
                    severity="error" if release else "warning",
                    message=f"control: {value} is a Kalico-specific documented mode, not an upstream Klipper {release or 'release'} mode. Verify support and tuning for the installed Kalico commit.",
                    section=section.name,
                    option=option,
                    line=section.lines.get(option, section.line),
                    source_url=KALICO,
                )
            )
    return checks
