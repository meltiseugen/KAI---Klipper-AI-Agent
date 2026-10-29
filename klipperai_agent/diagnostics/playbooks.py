"""Deterministic recovery guidance selected by observed signatures, not model guesses."""

from klipperai_agent.domain.recovery import RecoveryPlaybook

_CONFIG = "https://www.klipper3d.org/Config_Reference.html"
_CHECKS = "https://www.klipper3d.org/Config_checks.html"


def _plan(
    name: str,
    title: str,
    evidence: list[str],
    steps: list[str],
    verify: str,
    stop: str,
    url: str = _CHECKS,
) -> RecoveryPlaybook:
    return RecoveryPlaybook(
        id=name,
        title=title,
        required_evidence=evidence,
        steps=steps,
        verification=[verify],
        stop_conditions=[stop],
        source_urls=[url],
    )


_PLANS = {
    "communication": _plan(
        "mcu-communication",
        "MCU communication or scheduling failure",
        [
            "First shutdown and preceding statistics",
            "Affected MCU and USB/CAN/UART configuration",
            "Incident-timed host/kernel evidence",
        ],
        [
            "Identify the affected MCU and incident; preserve the log before retrying.",
            "Compare pre-stop counter deltas, host scheduling and correlated USB/CAN/power events; current status cannot rule out a past fault.",
            "Inspect the identified link and power connections manually with power off; choose a fix only when evidence supports it.",
        ],
        "After a supported manual correction, compare fresh logs under a supervised equivalent workload for recurrence and counter increases.",
        "Stop if power or wiring is suspect. Never increase safety timeouts or disable protections to hide the fault.",
        "https://www.klipper3d.org/FAQ.html",
    ),
    "thermal": _plan(
        "temperature-safety",
        "Temperature sensor or heater verification failure",
        [
            "Cited heater/sensor and first error",
            "Temperature history around the incident",
            "Active sensor and heater sections",
        ],
        [
            "Identify the sensor/heater from the cited evidence; do not assume a wiring fault from the error alone.",
            "Inspect sensor type and pin configuration against the actual hardware; inspect connections with power off.",
            "Have the user resolve sensor, heater power or mechanical faults before any supervised thermal verification.",
        ],
        "Confirm plausible ambient readings first; any later supervised heating check must show stable readings and no recurring verification fault.",
        "Stop if readings are implausible, heating is uncontrolled or wiring is damaged. Do not bypass verify_heater or temperature limits.",
    ),
    "homing": _plan(
        "homing-probe",
        "Homing or probe state failure",
        [
            "First homing/probe error and affected axis",
            "Endstop/probe config and macro order",
            "Manually observed endstop state and clearance",
        ],
        [
            "Check the affected endstop/probe state and mechanical release before movement.",
            "Compare wiring, polarity, homing direction and macro order with the active configuration.",
            "Only after clearance and state are verified should the user consider a supervised homing/probing check.",
        ],
        "The expected endstop state changes reliably and a supervised check completes without the original error.",
        "Stop if state is inconsistent or clearance is unknown. Do not force a homed state or enlarge travel to suppress the error.",
    ),
    "probe_repeatability": _plan(
        "probe-repeatability",
        "Probe samples outside tolerance",
        [
            "Actual samples and retry outcome",
            "Probe type and sampling configuration",
            "Mounting, surface and temperature conditions",
        ],
        [
            "Distinguish a retry notice from a terminal sampling failure.",
            "Inspect mounting, surface cleanliness, mechanical play and temperature conditions before changing sample settings.",
            "Compare repeated measurements under consistent conditions using the installed probe's documented manual procedure.",
        ],
        "A supervised repeatability check remains within the justified existing tolerance without repeated retries.",
        "Stop when probe state or clearance is uncertain. Do not widen tolerance merely to conceal unstable measurements.",
        "https://www.klipper3d.org/Probe_Calibrate.html",
    ),
    "driver": _plan(
        "tmc-driver",
        "TMC driver fault or register communication failure",
        [
            "Driver identity and complete register flags",
            "UART/SPI pins, address and configured current",
            "Exact board/driver documentation",
        ],
        [
            "Interpret the complete driver flags; a driver error does not by itself establish overheating.",
            "Compare UART/SPI configuration, jumpers, motor power and current with the actual board/driver documentation.",
            "Inspect motor and bus connections with power off before choosing a manual correction.",
        ],
        "Fresh read-only driver observations are consistent and the original register/fault error does not recur during a supervised check.",
        "Stop for damaged wiring or abnormal heat. Never disconnect a motor while its driver is powered.",
        "https://www.klipper3d.org/TMC_Drivers.html",
    ),
    "extrusion": _plan(
        "extrusion-guard",
        "Extrusion safety rejection",
        [
            "Rejected command and preceding slicer/macro commands",
            "Extruder temperature and active configuration",
            "G-code units and absolute/relative extrusion mode",
        ],
        [
            "Identify whether the rejection concerns cold extrusion, cross-section or extrusion-only distance.",
            "Compare the command's extrusion mode, units, purge/retraction amount and temperature-wait ordering with the intended operation.",
            "Correct the originating slicer/macro manually after checking the material and hardware requirements.",
        ],
        "The corrected command sequence respects the existing temperature and extrusion guards in a supervised check.",
        "Stop when temperature readings or extrusion intent are uncertain. Do not lower min_extrude_temp or raise extrusion limits just to bypass the rejection.",
        _CONFIG + "#extruder",
    ),
    "motion": _plan(
        "motion-limits",
        "Move outside configured travel",
        [
            "Rejected coordinates and originating command",
            "Axis limits, offsets and mesh bounds",
            "Homing state and physical travel",
        ],
        [
            "Trace the rejected coordinates to the slicer, macro or probe/mesh operation.",
            "Compare coordinates, offsets and homing state with the active configuration and physical travel.",
            "Correct the originating command or supported setting manually only after checking clearance.",
        ],
        "A supervised corrected operation stays within verified physical and configured travel.",
        "Stop if clearance is unknown. Do not enlarge limits merely to remove the error.",
    ),
    "config": _plan(
        "configuration-startup",
        "Configuration startup or compatibility failure",
        [
            "First startup error",
            "Cited config file/section and include order",
            "Installed host/MCU versions when protocol compatibility is involved",
        ],
        [
            "Preserve the first startup error and inspect the exact cited on-disk configuration.",
            "Check include paths, active placeholders and installed firmware compatibility; do not invent hardware values.",
            "Prepare and review any correction manually, then rerun the read-only audit; firmware updates require a separate manual plan.",
        ],
        "A fresh audit and user-observed startup no longer report the original fault; on-disk checks alone do not verify loaded firmware.",
        "Stop if hardware values or firmware targets are unknown. Never apply a generated placeholder as a real pin or calibration value.",
        _CONFIG,
    ),
    "service": _plan(
        "host-service",
        "Printer host service failure",
        ["Service status and paired journal", "First startup error and recent host changes"],
        [
            "Read the first error in the paired service journal rather than treating the final exit status as its cause.",
            "Check the cited dependency, configuration or permissions manually.",
            "After a supported correction, the user decides when a manual service restart is appropriate.",
        ],
        "Fresh service observations are healthy and the first failure no longer recurs in the journal.",
        "Stop if a print is active or the required correction is uncertain; this playbook never restarts a service.",
        "https://www.klipper3d.org/FAQ.html",
    ),
}

_FAMILIES = {
    **dict.fromkeys(
        (
            "mcu_timer_too_close",
            "mcu_communication_lost",
            "mcu_homing_timeout",
            "mcu_past_timer",
            "mcu_connect_failure",
        ),
        "communication",
    ),
    **dict.fromkeys(("adc_out_of_range", "heater_heating_failure"), "thermal"),
    **dict.fromkeys(
        (
            "bltouch_probe_failure",
            "probe_failure",
            "homing_no_trigger",
            "homing_endstop_still_triggered",
            "must_home_first",
        ),
        "homing",
    ),
    **dict.fromkeys(("tmc_driver_fault", "tmc_communication_failure"), "driver"),
    **dict.fromkeys(
        ("cold_extrusion", "extrusion_cross_section", "extrude_only_distance"), "extrusion"
    ),
    **dict.fromkeys(
        ("config_file_missing", "config_placeholder_value", "mcu_protocol_mismatch"), "config"
    ),
    "probe_samples_tolerance": "probe_repeatability",
    "move_out_of_range": "motion",
    "systemd_service_failed": "service",
}


def recovery_playbook(code: str) -> RecoveryPlaybook | None:
    family = _FAMILIES.get(code)
    return _PLANS[family].copy(deep=True) if family else None
