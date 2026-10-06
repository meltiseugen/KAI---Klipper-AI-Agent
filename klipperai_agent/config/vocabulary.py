from __future__ import annotations

import re
from typing import Literal

from klipperai_agent.domain.proposals import ConfigFeature as ConfigFeature

ConfigRequestIntent = Literal["generate", "locate", "explain", "edit"]


_FEATURE_KEYWORDS: tuple[tuple[ConfigFeature, tuple[str, ...]], ...] = (
    ("bed_mesh", ("bed mesh", "bed_mesh", "mesh leveling", "adaptive mesh")),
    ("filament", ("filament sensor", "filament switch", "runout", "motion sensor")),
    ("input_shaper", ("input shaper", "resonance", "adxl", "accelerometer")),
    ("canbus", ("canbus", "can bus", "can toolhead", "ebb", "utoc")),
    ("probe", ("bltouch", "probe", "klicky", "inductive", "cartographer", "beacon", "eddy")),
    ("sensor", ("sensor", "thermistor", "filament switch", "filament sensor")),
    ("macro", ("macro", "gcode_macro", "start print", "end print")),
    ("heater", ("heater", "heater_fan", "temperature_fan", "hotend fan", "bed heater")),
    ("extruder", ("extruder", "rotation_distance", "pressure advance", "pressure_advance")),
    (
        "stepper",
        ("stepper", "tmc", "motor current", "driver current", "x axis", "y axis", "z axis"),
    ),
    ("fan", ("fan", "blower", "part cooling", "controller fan")),
)


_FEATURE_SECTION_PREFIXES: dict[ConfigFeature, tuple[str, ...]] = {
    "fan": ("fan", "fan_generic", "heater_fan", "controller_fan", "temperature_fan"),
    "macro": ("gcode_macro", "delayed_gcode"),
    "sensor": ("temperature_sensor", "thermistor", "adc_temperature"),
    "probe": ("probe", "bltouch", "beacon", "cartographer", "probe_eddy_current"),
    "heater": ("extruder", "heater_bed", "heater_fan", "temperature_fan"),
    "input_shaper": ("input_shaper", "resonance_tester", "adxl345", "lis2dw"),
    "bed_mesh": ("bed_mesh",),
    "filament": ("filament_switch_sensor", "filament_motion_sensor"),
    "canbus": ("mcu",),
    "stepper": ("stepper_", "tmc"),
    "extruder": ("extruder", "extruder_stepper"),
    "generic": (),
}


_DIRECT_SECTION_PATTERN = re.compile(r"\[([^\]]+)\]")


_SECTION_LINE_PATTERN = re.compile(r"^\s*\[[^\]\n]+\]\s*$")


_MACRO_WORD_PATTERN = re.compile(r"\b(?:gcode[_\s-]*)?macro\b(?!-)", re.IGNORECASE)


_MACRO_IDENTIFIER_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[_-][A-Za-z0-9]+)+\b")


_MACRO_COMMAND_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]{2,}\b")


_MACRO_NAME_BOUNDARY_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "can",
    "configured",
    "declared",
    "defined",
    "definition",
    "do",
    "does",
    "file",
    "find",
    "for",
    "gcode",
    "has",
    "have",
    "i",
    "in",
    "is",
    "locate",
    "located",
    "macro",
    "me",
    "my",
    "on",
    "please",
    "show",
    "that",
    "the",
    "this",
    "what",
    "where",
    "which",
    "you",
    "your",
}


_MACRO_NAME_LEADING_WORDS = {
    "called",
    "named",
    "is",
    "as",
    "for",
    "the",
    "my",
    "a",
    "an",
}


_LOOKUP_CORRECTION_WORDS = ("i mean", "i meant", "actually", "rather", "instead", "sorry")


_EXPLAIN_INTENT_WORDS = (
    "called by",
    "explain",
    "how does",
    "tell me about",
    "used by",
    "what does",
    "what is",
    "where is used",
    "where is it used",
)


_EDIT_INTENT_WORDS = (
    "change",
    "disable",
    "edit",
    "enable",
    "modify",
    "remove",
    "rename",
    "replace",
    "turn off",
    "turn on",
    "update",
)
