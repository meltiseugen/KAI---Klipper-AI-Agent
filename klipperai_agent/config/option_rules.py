"""Small, explicit reference constraints; not a complete firmware schema.

Sources and version scope are documented in docs/configuration-review.md.
Unknown options remain unverified so extensions are not declared invalid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

REFERENCE = "https://www.klipper3d.org/Config_Reference.html"
CHANGES = "https://www.klipper3d.org/Config_Changes.html"
KALICO = "https://docs.kalico.gg/Config_Reference.html"


@dataclass(frozen=True)
class OptionRule:
    kind: str = "text"
    minimum: float | None = None
    maximum: float | None = None
    above: bool = False
    below: bool = False
    choices: tuple[str, ...] = ()


TEXT = OptionRule()
NUMBER = OptionRule("number")
POSITIVE = OptionRule("number", minimum=0, above=True)
NONNEGATIVE = OptionRule("number", minimum=0)
FRACTION = OptionRule("number", minimum=0, maximum=1)
POWER = OptionRule("number", minimum=0, maximum=1, above=True)
INTEGER = OptionRule("integer", minimum=1)
BOOLEAN = OptionRule("boolean")
FAN = {
    "pin": TEXT,
    "enable_pin": TEXT,
    "max_power": POWER,
    "shutdown_speed": FRACTION,
    "cycle_time": POSITIVE,
    "hardware_pwm": BOOLEAN,
    "kick_start_time": NONNEGATIVE,
    "off_below": FRACTION,
    "tachometer_pin": TEXT,
    "tachometer_ppr": INTEGER,
    "tachometer_poll_interval": POSITIVE,
}
HEATER = {
    "heater_pin": TEXT,
    "sensor_type": TEXT,
    "sensor_pin": TEXT,
    "min_temp": NUMBER,
    "max_temp": NUMBER,
    "max_power": POWER,
    "control": OptionRule("choice", choices=("pid", "watermark")),
    "pid_kp": NONNEGATIVE,
    "pid_ki": NONNEGATIVE,
    "pid_kd": NONNEGATIVE,
    "smooth_time": POSITIVE,
    "pwm_cycle_time": POSITIVE,
    "pullup_resistor": POSITIVE,
    "inline_resistor": NONNEGATIVE,
    "max_delta": POSITIVE,
}
STEPPER = {
    "step_pin": TEXT,
    "dir_pin": TEXT,
    "enable_pin": TEXT,
    "rotation_distance": POSITIVE,
    "microsteps": INTEGER,
    "full_steps_per_rotation": INTEGER,
    "gear_ratio": TEXT,
    "endstop_pin": TEXT,
    "position_endstop": NUMBER,
    "position_min": NUMBER,
    "position_max": NUMBER,
    "homing_speed": POSITIVE,
    "second_homing_speed": POSITIVE,
    "homing_retract_dist": NONNEGATIVE,
    "homing_positive_dir": BOOLEAN,
}
PROBE = {
    "pin": TEXT,
    "x_offset": NUMBER,
    "y_offset": NUMBER,
    "z_offset": NUMBER,
    "speed": POSITIVE,
    "lift_speed": POSITIVE,
    "samples": INTEGER,
    "sample_retract_dist": POSITIVE,
    "samples_tolerance": NONNEGATIVE,
    "samples_tolerance_retries": OptionRule("integer", minimum=0),
    "samples_result": OptionRule("choice", choices=("median", "average")),
    "activate_gcode": TEXT,
    "deactivate_gcode": TEXT,
    "deactivate_on_each_sample": BOOLEAN,
}
SHAPERS = ("zv", "mzv", "zvd", "ei", "2hump_ei", "3hump_ei")
RULES = {
    "printer": {
        "kinematics": TEXT,
        "max_velocity": POSITIVE,
        "max_accel": POSITIVE,
        "square_corner_velocity": NONNEGATIVE,
        "minimum_cruise_ratio": OptionRule("number", minimum=0, maximum=1, below=True),
        "max_accel_to_decel": POSITIVE,
        "max_z_velocity": POSITIVE,
        "max_z_accel": POSITIVE,
    },
    "fan": FAN,
    "fan_generic": FAN,
    "heater_fan": {**FAN, "heater": TEXT, "heater_temp": NUMBER, "fan_speed": FRACTION},
    "controller_fan": {
        **FAN,
        "heater": TEXT,
        "stepper": TEXT,
        "fan_speed": FRACTION,
        "idle_speed": FRACTION,
        "idle_timeout": NONNEGATIVE,
    },
    "temperature_fan": {
        **FAN,
        **{
            key: HEATER[key]
            for key in (
                "sensor_type",
                "sensor_pin",
                "min_temp",
                "max_temp",
                "control",
                "pid_kp",
                "pid_ki",
                "pid_kd",
            )
        },
        "target_temp": NUMBER,
        "min_speed": FRACTION,
        "max_speed": FRACTION,
    },
    "heater_bed": HEATER,
    "heater_generic": HEATER,
    "stepper": STEPPER,
    "extruder": {
        **STEPPER,
        **HEATER,
        "nozzle_diameter": POSITIVE,
        "filament_diameter": POSITIVE,
        "pressure_advance": NONNEGATIVE,
        "pressure_advance_smooth_time": OptionRule("number", minimum=0, maximum=0.2, above=True),
        "min_extrude_temp": NONNEGATIVE,
        "max_extrude_cross_section": POSITIVE,
        "max_extrude_only_distance": NUMBER,
        "max_extrude_only_velocity": POSITIVE,
        "max_extrude_only_accel": POSITIVE,
    },
    "temperature_sensor": {
        key: HEATER[key] for key in ("sensor_type", "sensor_pin", "min_temp", "max_temp")
    },
    "probe": PROBE,
    "bltouch": {
        **{key: value for key, value in PROBE.items() if key != "pin"},
        "sensor_pin": TEXT,
        "control_pin": TEXT,
        "pin_move_time": POSITIVE,
        "stow_on_each_sample": BOOLEAN,
        "probe_with_touch_mode": BOOLEAN,
    },
    "input_shaper": {
        "shaper_type": OptionRule("choice", choices=SHAPERS),
        **{f"shaper_type_{axis}": OptionRule("choice", choices=SHAPERS) for axis in ("x", "y")},
        **{f"shaper_freq_{axis}": NONNEGATIVE for axis in ("x", "y")},
        **{f"damping_ratio_{axis}": FRACTION for axis in ("x", "y")},
    },
    "bed_mesh": {
        "speed": POSITIVE,
        "horizontal_move_z": NUMBER,
        "mesh_min": OptionRule("pair"),
        "mesh_max": OptionRule("pair"),
        "mesh_radius": POSITIVE,
        "mesh_origin": OptionRule("pair"),
        "probe_count": OptionRule("integer_pair", minimum=3),
        "mesh_pps": OptionRule("integer_pair", minimum=0),
        "algorithm": OptionRule("choice", choices=("lagrange", "bicubic")),
        "bicubic_tension": OptionRule("number", minimum=0, maximum=2),
        "fade_start": NUMBER,
        "fade_end": NUMBER,
        "fade_target": NUMBER,
        "zero_reference_position": OptionRule("pair"),
        "relative_reference_index": OptionRule("integer", minimum=0),
    },
    "gcode_macro": {"gcode": TEXT, "description": TEXT, "rename_existing": TEXT},
    "delayed_gcode": {"gcode": TEXT, "initial_duration": NONNEGATIVE},
    "output_pin": {
        "pin": TEXT,
        "pwm": BOOLEAN,
        "value": NUMBER,
        "shutdown_value": NUMBER,
        "cycle_time": POSITIVE,
        "hardware_pwm": BOOLEAN,
        "scale": POSITIVE,
        "static_value": NUMBER,
        "maximum_mcu_duration": NONNEGATIVE,
    },
}
REQUIRED = {
    "fan": ("pin",),
    "fan_generic": ("pin",),
    "heater_fan": ("pin",),
    "controller_fan": ("pin",),
    "temperature_fan": ("pin", "sensor_type", "control", "min_temp", "max_temp"),
    "heater_bed": ("heater_pin", "sensor_type", "control", "min_temp", "max_temp"),
    "heater_generic": ("heater_pin", "sensor_type", "control", "min_temp", "max_temp"),
    "temperature_sensor": ("sensor_type",),
    "probe": ("pin", "z_offset"),
    "bltouch": ("sensor_pin", "control_pin", "z_offset"),
    "gcode_macro": ("gcode",),
    "delayed_gcode": ("gcode",),
    "output_pin": ("pin",),
}


def section_family(name: str) -> str:
    family = name.split()[0].lower()
    if re.fullmatch(r"stepper_[a-z]\d*", family):
        return "stepper"
    if re.fullmatch(r"extruder\d*", family):
        return "extruder"
    return family
