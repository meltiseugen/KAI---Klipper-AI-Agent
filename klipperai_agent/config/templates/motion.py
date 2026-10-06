from __future__ import annotations

from klipperai_agent.config.requests import ConfigPromptPayload
from klipperai_agent.domain.proposals import ConfigProposal


class CanbusProposal:
    def build(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal:
        if not payload.profile.canbus_enabled:
            warnings.append(
                "The saved printer profile does not show CAN enabled yet. Treat this as an initial CAN bring-up, not an incremental edit to an existing CAN topology."
            )
        return ConfigProposal(
            feature="canbus",
            title="Starter CAN toolhead MCU section",
            target_file="klipperai/canbus.cfg",
            config=(
                "[mcu toolhead]\n"
                "canbus_uuid: <CANBUS_UUID>\n\n"
                "[temperature_sensor toolhead_mcu]\n"
                "sensor_type: temperature_mcu\n"
                "sensor_mcu: toolhead\n"
            ),
            rationale="A CAN toolhead setup usually starts with an MCU declaration and a simple sensor or pin consumer that validates the link.",
            assumptions=[
                "You already know the toolhead board CAN UUID or will fetch it separately.",
            ],
            warnings=[
                "Replace <CANBUS_UUID> with the detected UUID for your toolhead board.",
                *warnings,
            ],
        )


class StepperProposal:
    def build(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal:
        return ConfigProposal(
            feature="stepper",
            title="Starter TMC driver block",
            target_file="klipperai/stepper.cfg",
            config=(
                "[tmc2209 stepper_x]\n"
                "uart_pin: <UART_PIN>\n"
                "run_current: <RUN_CURRENT>\n"
                "hold_current: <HOLD_CURRENT>\n"
                "sense_resistor: 0.110\n"
            ),
            rationale="A driver-current tuning request usually needs a TMC section scaffold more than a whole kinematics rewrite.",
            assumptions=[
                "This is for a TMC2209-style UART-configured driver on one axis.",
            ],
            warnings=[
                "Replace the UART pin and current values with board-specific values.",
                *warnings,
            ],
        )


class ExtruderProposal:
    def build(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal:
        return ConfigProposal(
            feature="extruder",
            title="Starter extruder tuning block",
            target_file="klipperai/extruder.cfg",
            config=(
                "[extruder]\n"
                "step_pin: <STEP_PIN>\n"
                "dir_pin: <DIR_PIN>\n"
                "enable_pin: <ENABLE_PIN>\n"
                "rotation_distance: <ROTATION_DISTANCE>\n"
                "nozzle_diameter: 0.400\n"
                "filament_diameter: 1.750\n"
            ),
            rationale="Extruder setup requests often need a compact scaffold with motion pins and the most critical calibration value, rotation_distance.",
            assumptions=[
                "You want a fresh extruder section scaffold rather than a narrow tuning-only change.",
            ],
            warnings=[
                "Replace all placeholder pins and rotation_distance with your real hardware values.",
                *warnings,
            ],
        )
