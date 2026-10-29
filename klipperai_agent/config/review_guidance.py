"""Ordered manual checks chosen from the actual sections, never model feature labels."""

from klipperai_agent.config.option_rules import section_family
from klipperai_agent.config.review_parser import ReviewSection


def manual_verification(sections: list[ReviewSection]) -> list[str]:
    families = {section_family(section.name) for section in sections}
    steps = [
        "Resolve blocking issues and unverified options against documentation for the installed firmware fork and exact version/commit.",
        "Back up the target and included config files. Compare and merge only the proposed sections; preserve unrelated options, comments and SAVE_CONFIG data.",
        "Check the target include path and remove duplicate definitions. Recheck this proposal before editing; request a new draft if config or firmware has changed.",
    ]
    if any(
        option.endswith("_pin") or option == "pin"
        for section in sections
        for option in section.values
    ):
        steps.append(
            "With power isolated before wiring work, verify the board revision, MCU alias, pin ownership, polarity and connector voltage/current against its manual."
        )
    if families & {
        "heater_bed",
        "heater_generic",
        "extruder",
        "temperature_sensor",
        "temperature_fan",
    }:
        steps.append(
            "Verify the exact sensor model and sensible room-temperature readings before enabling any heater. Keep thermal protection enabled; use measured tuning and hardware-rated temperature/power limits."
        )
    if families & {"fan", "fan_generic", "heater_fan", "controller_fan", "temperature_fan"}:
        steps.append(
            "Verify fan voltage, rated current and cooling role; check the intended shutdown behavior and confirm the correct fan responds during a supervised manual test."
        )
    if families & {"stepper", "extruder", "probe", "bltouch", "bed_mesh", "printer"}:
        steps.append(
            "Before any manual homing or movement, clear the travel area and verify endstop/probe states, direction, offsets and reachable limits using the firmware's configuration-check guide."
        )
    if families & {"probe", "bltouch", "bed_mesh"}:
        steps.append(
            "Check probe offsets and every proposed mesh edge against nozzle/probe reach and clamps. Recalibrate offsets/mesh using the procedure for this exact probe and firmware."
        )
    if "input_shaper" in families:
        steps.append(
            "Use measured resonance results for this printer and accelerometer placement. Recheck motion limits and recalibrate after relevant mechanical or firmware changes."
        )
    if families & {"gcode_macro", "delayed_gcode"}:
        steps.append(
            "Read every macro/Jinja branch and referenced macro, including renamed commands, parameters and saved variables. The review does not execute code or prove that its motion/heater commands are safe."
        )
    steps.append(
        "After manual editing, inspect firmware config errors before use. Perform only the relevant supervised checks from the matching firmware guide, with a way to stop immediately; restore the backup if checks fail."
    )
    return steps
