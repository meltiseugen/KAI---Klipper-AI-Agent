from __future__ import annotations

from klipperai_agent.config.requests import ConfigPromptPayload
from klipperai_agent.domain.proposals import ConfigProposal


class FanProposal:
    def build(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal:
        if payload.snapshot.has_section_prefix("fan") or payload.snapshot.has_section_prefix(
            "heater_fan"
        ):
            warnings.append(
                "A fan-related section already exists in the current config. Check for overlap before adding another one."
            )
        return ConfigProposal(
            feature="fan",
            title="Generic PWM fan section",
            target_file="klipperai/fan.cfg",
            config=(
                "[fan]\npin: <FAN_PIN>\nmax_power: 1.0\nkick_start_time: 0.5\noff_below: 0.10\n"
            ),
            rationale="Baseline controllable fan configuration with the most common tuning options exposed.",
            assumptions=[
                "This is a standard PWM-controllable fan.",
                "You will replace <FAN_PIN> with the actual MCU pin.",
            ],
            warnings=["Replace <FAN_PIN> with the real MCU pin name before using this.", *warnings],
        )


class SensorProposal:
    def build(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal:
        return ConfigProposal(
            feature="sensor",
            title="Starter temperature sensor section",
            target_file="klipperai/sensor.cfg",
            config=(
                "[temperature_sensor auxiliary_sensor]\n"
                "sensor_type: <SENSOR_TYPE>\n"
                "sensor_pin: <SENSOR_PIN>\n"
                "min_temp: 0\n"
                "max_temp: 100\n"
            ),
            rationale="A generic temperature sensor section is a common starting point when adding enclosure, chamber, or auxiliary sensors.",
            assumptions=[
                "This request is for a passive temperature sensor rather than a probing or filament sensor.",
            ],
            warnings=[
                "Replace <SENSOR_TYPE> and <SENSOR_PIN> with the actual hardware values.",
                *warnings,
            ],
        )


class HeaterProposal:
    def build(self, payload: ConfigPromptPayload, warnings: list[str]) -> ConfigProposal:
        return ConfigProposal(
            feature="heater",
            title="Starter heater fan section",
            target_file="klipperai/heater.cfg",
            config=(
                "[heater_fan hotend_cooling]\n"
                "pin: <FAN_PIN>\n"
                "heater: extruder\n"
                "heater_temp: 50.0\n"
                "fan_speed: 1.0\n"
            ),
            rationale="A heater_fan section is a common controlled-cooling pattern for hotend fans and similar temperature-driven cooling use cases.",
            assumptions=[
                "This request is closer to a heater-driven fan or cooling behavior than to core heater pin setup.",
            ],
            warnings=["Replace <FAN_PIN> with the correct MCU output pin.", *warnings],
        )
