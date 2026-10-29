"""Pure, partial validation of proposed values and their observed section context."""

from __future__ import annotations

import math
import re
from typing import Literal

from klipperai_agent.config.models import ConfigSnapshot
from klipperai_agent.config.option_rules import (
    REFERENCE,
    REQUIRED,
    RULES,
    OptionRule,
    section_family,
)
from klipperai_agent.config.review_parser import ReviewSection, parse_review_config
from klipperai_agent.config.review_versions import version_checks
from klipperai_agent.domain.proposals import ReviewCheck, ReviewFirmware


def number_values(value: str, rule: OptionRule) -> list[float]:
    parts = [part.strip() for part in value.split(",")]
    expected = (1, 2) if rule.kind == "integer_pair" else (2,) if rule.kind == "pair" else (1,)
    if len(parts) not in expected or (
        rule.kind.startswith("integer") and any(not re.fullmatch(r"[+-]?\d+", p) for p in parts)
    ):
        raise ValueError("Wrong number or type of values.")
    numbers = [float(part) for part in parts]
    if not all(math.isfinite(number) for number in numbers):
        raise ValueError("Values must be finite.")
    return numbers


def value_problem(value: str, rule: OptionRule) -> str:
    if rule.kind == "text":
        return ""
    if rule.kind == "boolean":
        return (
            ""
            if value.lower() in {"0", "1", "true", "false", "yes", "no", "on", "off"}
            else "Use a boolean (True/False, yes/no, on/off or 1/0)."
        )
    if rule.kind == "choice":
        return "" if value in rule.choices else f"Reference choices: {', '.join(rule.choices)}."
    try:
        numbers = number_values(value, rule)
    except ValueError:
        return f"Expected finite {rule.kind.replace('_', ' ')} values."
    for number in numbers:
        if rule.minimum is not None and (
            number < rule.minimum or (rule.above and number == rule.minimum)
        ):
            return f"Value must be {'greater than' if rule.above else 'at least'} {rule.minimum:g}."
        if rule.maximum is not None and (
            number > rule.maximum or (rule.below and number == rule.maximum)
        ):
            return f"Value must be {'less than' if rule.below else 'at most'} {rule.maximum:g}."
    return ""


def _check(
    section: ReviewSection,
    option: str,
    code: str,
    severity: Literal["error", "warning", "info"],
    message: str,
) -> ReviewCheck:
    return ReviewCheck(
        code=code,
        severity=severity,
        message=message,
        section=section.name,
        option=option,
        line=section.lines.get(option, section.line),
        source_url=f"{REFERENCE}#{section_family(section.name)}",
    )


def _relationships(
    section: ReviewSection, family: str, effective: dict[str, str]
) -> list[ReviewCheck]:
    checks = []
    pairs = []
    if family in {
        "heater_bed",
        "heater_generic",
        "extruder",
        "temperature_sensor",
        "temperature_fan",
    }:
        pairs.append(("min_temp", "max_temp", False))
    if family == "stepper":
        pairs.append(("position_min", "position_max", False))
    if family == "temperature_fan":
        pairs.append(("min_speed", "max_speed", True))
    for low, high, equal_allowed in pairs:
        if not (set(section.values) & {low, high}) or not all(
            key in effective for key in (low, high)
        ):
            continue
        try:
            lower, upper = (
                number_values(effective[key], OptionRule("number"))[0] for key in (low, high)
            )
        except ValueError:
            continue
        if lower > upper or (lower == upper and not equal_allowed):
            checks.append(
                _check(
                    section,
                    high,
                    "option_order",
                    "error",
                    f"{high} must be {'at least' if equal_allowed else 'greater than'} {low}, including the observed options retained during a manual merge.",
                )
            )
    if (
        family in {"heater_bed", "heater_generic", "extruder"}
        and "control" in section.values
        and effective["control"] == "pid"
    ):
        missing = [name for name in ("pid_kp", "pid_ki", "pid_kd") if not effective.get(name)]
        if missing:
            checks.append(
                _check(
                    section,
                    "control",
                    "pid_coefficients",
                    "error",
                    f"PID control needs measured coefficients: {', '.join(missing)}. Do not invent tuning values.",
                )
            )
    if (
        family == "bed_mesh"
        and set(section.values) & {"mesh_min", "mesh_max"}
        and all(key in effective for key in ("mesh_min", "mesh_max"))
    ):
        try:
            low_xy, high_xy = (
                number_values(effective[key], OptionRule("pair"))
                for key in ("mesh_min", "mesh_max")
            )
        except ValueError:
            return checks
        if any(low >= high for low, high in zip(low_xy, high_xy)):
            checks.append(
                _check(
                    section,
                    "mesh_max",
                    "mesh_bounds",
                    "error",
                    "mesh_max must exceed mesh_min on both axes; also check probe offsets and physical reach manually.",
                )
            )
    return checks


def review_options(
    sections: list[ReviewSection], snapshot: ConfigSnapshot, path: str, firmware: ReviewFirmware
) -> list[ReviewCheck]:
    checks: list[ReviewCheck] = []
    existing: dict[str, dict[str, str]] = {}
    for document in snapshot.documents:
        if document.path == path and not document.truncated:
            parsed, errors = parse_review_config(document.content)
            if not errors:
                existing = {section.name.casefold(): section.values for section in parsed}
    for section in sections:
        family = section_family(section.name)
        rules = RULES.get(family, {})
        if not rules:
            checks.append(
                _check(
                    section,
                    "",
                    "section_unverified",
                    "warning",
                    "This section has no bundled option schema. Verify the installed extension/fork documentation.",
                )
            )
        for option, value in section.values.items():
            rule = rules.get(option)
            if family == "gcode_macro" and option.startswith("variable_"):
                checks.append(
                    _check(
                        section,
                        option,
                        "macro_variable",
                        "warning",
                        "Check the variable's Python literal and lowercase name manually; macro code is not executed by this review.",
                    )
                )
                continue
            if (
                family in {"heater_bed", "heater_generic", "extruder"}
                and option == "control"
                and value in {"mpc", "pid_v", "dual_loop_pid"}
            ):
                continue  # The fork/version check owns these modes.
            if rule is None:
                if rules:
                    checks.append(
                        _check(
                            section,
                            option,
                            "option_unverified",
                            "warning",
                            "This option is outside the bundled schema; check spelling and exact firmware/extension support.",
                        )
                    )
                continue
            if rule.kind == "text":
                continue  # Recognizing a name does not validate pins, sensor types, or code.
            if "{" in value or "\n" in value:
                checks.append(
                    _check(
                        section,
                        option,
                        "value_unverified",
                        "warning",
                        "An expression or multiline value requires manual verification. It was not evaluated.",
                    )
                )
                continue
            problem = value_problem(value, rule)
            checks.append(
                _check(
                    section,
                    option,
                    "option_value",
                    "error" if problem else "info",
                    problem
                    or "Matches the bundled type/range check; installed firmware and physical limits still need verification.",
                )
            )
        effective = {**existing.get(section.name.casefold(), {}), **section.values}
        for option in REQUIRED.get(family, ()):
            if not effective.get(option):
                checks.append(
                    _check(
                        section,
                        option,
                        "required_option",
                        "error",
                        f"Provide {option} in this section or confirm it in a complete observed section before merging.",
                    )
                )
        checks.extend(_relationships(section, family, effective))
        checks.extend(version_checks(section, family, firmware))
    return checks
