"""Reported runtime signatures; matching establishes observations, not causes."""

import re

from klipperai_agent.domain.evidence import Severity

RUNTIME_SIGNATURES: tuple[tuple[str, re.Pattern[str], Severity, str, str], ...] = (
    (
        "cold_extrusion",
        re.compile(r"\bExtrude below minimum temp\b", re.IGNORECASE),
        "high",
        "Klipper rejected extrusion below its configured minimum temperature; the command order and sensor evidence need inspection.",
        "Inspect the originating macro/slicer temperature-wait sequence and sensor readings. Do not lower min_extrude_temp to bypass this guard.",
    ),
    (
        "extrusion_cross_section",
        re.compile(r"\bMove exceeds maximum extrusion\b", re.IGNORECASE),
        "medium",
        "A move exceeded the configured extrusion cross-section guard; this does not establish an extruder hardware fault.",
        "Compare the rejected command, extrusion mode, units, nozzle/filament settings and purge amount. Correct the source manually instead of raising the safety limit to hide the error.",
    ),
    (
        "extrude_only_distance",
        re.compile(r"\bExtrude only move too long\b", re.IGNORECASE),
        "medium",
        "An extrusion-only move exceeded its configured distance guard.",
        "Inspect absolute/relative extrusion mode, retraction and purge commands in the originating macro or slicer. Do not increase extrusion limits merely to bypass the rejection.",
    ),
    (
        "must_home_first",
        re.compile(r"\bMust home (?:axis first|before probe)\b", re.IGNORECASE),
        "medium",
        "Klipper rejected movement or probing because the required homing state was absent.",
        "Inspect macro order, current homing state and endstop/probe evidence. Verify clearance before the user attempts homing; do not force a homed state.",
    ),
    (
        "probe_samples_tolerance",
        re.compile(r"\bProbe samples exceed samples_tolerance\b", re.IGNORECASE),
        "medium",
        "Probe samples exceeded the configured tolerance after the allowed retries; the physical cause is unconfirmed.",
        "Compare samples, mounting, surface and temperature conditions with the probe configuration. Do not widen samples_tolerance just to conceal unstable measurements.",
    ),
    (
        "mcu_timer_too_close",
        re.compile(r"Timer too close", re.IGNORECASE),
        "high",
        "An MCU command missed its scheduling deadline; the message alone does not identify why.",
        "Investigate pre-shutdown host statistics, MCU communication counters and kernel events. Do not change acceleration or safety timeouts based on this message alone.",
    ),
    (
        "mcu_communication_lost",
        re.compile(
            r"Lost communication with MCU|Timeout with MCU|Communication interrupted",
            re.IGNORECASE,
        ),
        "critical",
        "Communication with an MCU was interrupted.",
        "Identify the affected MCU and transport, then correlate pre-stop log statistics with USB/CAN, power, memory and host scheduling evidence.",
    ),
    (
        "mcu_homing_timeout",
        re.compile(r"Communication timeout during homing", re.IGNORECASE),
        "high",
        "MCU communication exceeded the homing timing requirement.",
        "Inspect the probe/endstop and motor MCU assignments, communication latency and host scheduling; do not increase TRSYNC_TIMEOUT.",
    ),
    (
        "mcu_past_timer",
        re.compile(r"Rescheduled timer in the past|Stepper too far in past", re.IGNORECASE),
        "high",
        "An MCU could not schedule an operation in time.",
        "Preserve the first shutdown and preceding statistics; investigate host, link and MCU scheduling evidence before choosing a fix.",
    ),
    (
        "mcu_connect_failure",
        re.compile(r"mcu .*Unable to connect|Unable to connect to MCU", re.IGNORECASE),
        "critical",
        "Klipper cannot connect to one of the configured MCU devices.",
        "Verify USB or CAN connectivity, the serial path, power state, and firmware flashing target.",
    ),
    (
        "config_file_missing",
        re.compile(
            r"\bUnable to open config file\b|\bInclude file ['\"][^'\"]+['\"] does not exist\b",
            re.IGNORECASE,
        ),
        "high",
        "A configuration file could not be opened or an included file is missing.",
        "Check the cited path, include paths, file permissions, recent file moves and whether generated files exist on disk.",
    ),
    (
        "adc_out_of_range",
        re.compile(r"ADC out of range", re.IGNORECASE),
        "high",
        "A temperature sensor reading is outside the safe range.",
        "Inspect thermistor wiring, sensor type configuration, and any intermittent connector issues.",
    ),
    (
        "bltouch_probe_failure",
        re.compile(
            r"\bBLTouch (?:probe )?failed\b|\bFailed to verify BLTouch probe\b", re.IGNORECASE
        ),
        "medium",
        "BLTouch reported a deployment or sensor verification failure; the message may describe a retry.",
        "Check BLTouch wiring, pin assignments, probe offsets, and mechanical interference.",
    ),
    (
        "probe_failure",
        re.compile(r"(?<!BLTouch )\bprobe failed\b", re.IGNORECASE),
        "medium",
        "A probe operation reported a failure; the probe type and physical cause are not established.",
        "Identify the probe from the active configuration and inspect the surrounding error, wiring, configuration and mechanical clearance before further probing.",
    ),
    (
        "heater_heating_failure",
        re.compile(
            r"\bHeater ['\"]?(?P<component>[\w.:-]+)['\"]? not heating at expected rate\b",
            re.IGNORECASE,
        ),
        "high",
        "A heater failed its temperature verification check; the message alone does not establish the physical cause.",
        "Inspect the cited heater's temperature history, sensor configuration, heater power and connections with the printer safely powered down. Do not disable verify_heater or relax its limits to mask the fault.",
    ),
    (
        "homing_no_trigger",
        re.compile(
            r"\bNo trigger on (?P<component>[\w.:-]+) after full movement\b",
            re.IGNORECASE,
        ),
        "high",
        "An endstop or probe did not trigger during the commanded homing/probing travel.",
        "Identify the cited endstop/probe and manually verify its reported state, pin polarity, wiring, homing direction and physical clearance before another homing attempt. Do not extend travel limits solely to suppress this error.",
    ),
    (
        "homing_endstop_still_triggered",
        re.compile(
            r"\bEndstop (?P<component>[\w.:-]+) still triggered after retract\b",
            re.IGNORECASE,
        ),
        "high",
        "An endstop remained triggered after the homing retract; the message alone does not identify why.",
        "Manually inspect the cited endstop's state and release, pin polarity, wiring and configured retract distance. For sensorless homing inspect its driver-specific setup before retrying movement.",
    ),
    (
        "tmc_driver_fault",
        re.compile(r"\bTMC ['\"](?P<component>[^'\"]+)['\"] reports error:", re.IGNORECASE),
        "high",
        "A TMC stepper driver reported an error; interpret the cited register flags before choosing a cause.",
        "Preserve the driver name and complete register flags. Review cooling, configured current, motor power and connections against that driver's documentation; inspect wiring with power off. Do not assume every driver fault is overheating.",
    ),
    (
        "tmc_communication_failure",
        re.compile(
            r"\bUnable to (?:read|write) tmc (?:uart|spi) ['\"](?P<component>[^'\"]+)['\"] register\b",
            re.IGNORECASE,
        ),
        "high",
        "Klipper could not read or write a TMC driver register; the message alone does not prove a failed driver.",
        "Check the cited driver's UART/SPI configuration, address or chip select, board jumpers and motor power. Inspect connections with power off and compare the board/driver documentation before changing configuration.",
    ),
    (
        "mcu_protocol_mismatch",
        re.compile(r"\bMCU Protocol error\b|\bCommand format mismatch:", re.IGNORECASE),
        "high",
        "An MCU protocol error or command-format mismatch was reported; host/MCU firmware compatibility needs verification.",
        "Compare the host version and affected MCU build/version details in the surrounding log, including firmware forks and build targets. Plan any required matching firmware update manually; this finding does not authorize flashing or restarting.",
    ),
    (
        "move_out_of_range",
        re.compile(r"\bMove out of range:", re.IGNORECASE),
        "medium",
        "Klipper rejected a move outside its configured motion limits; the message alone does not identify the incorrect setting or command.",
        "Compare the cited coordinates with axis travel, homing state, probe offsets, mesh bounds and the originating slicer or macro command. Correct the cause manually; verify physical clearance before enlarging limits.",
    ),
    (
        "systemd_service_failed",
        re.compile(
            r"ActiveState=failed|Result=exit-code|Result=signal|Start request repeated too quickly",
            re.IGNORECASE,
        ),
        "critical",
        "A required printer host service is failing under systemd.",
        "Inspect the paired journalctl artifact, correct the startup failure, and restart the affected service.",
    ),
)
