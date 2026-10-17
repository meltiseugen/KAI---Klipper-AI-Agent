"""Finite, read-only status groups. Model arguments never become API paths."""

from typing import Any, Literal

from klipperai_agent.agent.tools.base import Tool, ToolArguments, ToolContext

GROUPS: dict[str, tuple[str, ...]] = {
    "sensors": (
        "temperature_sensor ",
        "temperature_fan ",
        "filament_switch_sensor ",
        "filament_motion_sensor ",
        "heaters",
    ),
    "fans": ("fan", "heater_fan ", "controller_fan ", "fan_generic ", "temperature_fan "),
    "motion": ("toolhead", "motion_report", "gcode_move", "probe", "quad_gantry_level", "z_tilt"),
    "bed_mesh": ("bed_mesh",),
    "mcu": ("mcu", "mcu ", "system_stats"),
}


class PrinterObjectsArguments(ToolArguments):
    group: Literal["sensors", "fans", "motion", "bed_mesh", "mcu"]


class PrinterObjectsTool(Tool[PrinterObjectsArguments]):
    name = "get_printer_objects"
    label = "Read printer component status"
    description = "Read a fixed group of available sensor, fan, motion, bed-mesh or MCU status objects. No commands or arbitrary object names. Missing objects are unavailable, not healthy."
    arguments_type = PrinterObjectsArguments

    async def execute(
        self, arguments: PrinterObjectsArguments, context: ToolContext
    ) -> dict[str, Any]:
        available = await context.moonraker.list_printer_objects()
        allowed = GROUPS[arguments.group]
        selected = sorted(
            {
                name
                for name in available
                if any(
                    name.startswith(prefix) if prefix.endswith(" ") else name == prefix
                    for prefix in allowed
                )
            }
        )
        if not selected:
            return {"error": "No supported objects in this group are currently available."}
        status = await context.moonraker.query_printer_objects(
            {name: None for name in selected[:24]}
        )
        context.moonraker_reachable = True
        return {"objects": selected[:24], "status": status, "truncated": len(selected) > 24}
