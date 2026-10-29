"""Reported faults, normal messages and provenance from bounded log excerpts."""

import pytest

from klipperai_agent.diagnostics.rules import RuleEngine
from klipperai_agent.domain.evidence import ArtifactInput


@pytest.mark.parametrize(
    ("message", "code", "severity", "component"),
    [
        ("MCU 'mcu' shutdown: Timer too close", "mcu_timer_too_close", "high", ""),
        ("Lost communication with MCU 'toolhead'", "mcu_communication_lost", "critical", ""),
        ("Timeout with MCU 'mcu'", "mcu_communication_lost", "critical", ""),
        ("Communication interrupted", "mcu_communication_lost", "critical", ""),
        ("Communication timeout during homing probe", "mcu_homing_timeout", "high", ""),
        ("Rescheduled timer in the past", "mcu_past_timer", "high", ""),
        ("Stepper too far in past", "mcu_past_timer", "high", ""),
        ("mcu 'mcu': Unable to connect", "mcu_connect_failure", "critical", ""),
        ("Unable to connect to MCU", "mcu_connect_failure", "critical", ""),
        ("Unable to open config file /config/printer.cfg", "config_file_missing", "high", ""),
        ("Include file '/config/probe.cfg' does not exist", "config_file_missing", "high", ""),
        ("MCU 'mcu' shutdown: ADC out of range", "adc_out_of_range", "high", ""),
        ("BLTouch failed to raise probe", "bltouch_probe_failure", "medium", ""),
        ("BLTouch probe failed", "bltouch_probe_failure", "medium", ""),
        ("BLTouch failed to verify sensor state; retrying.", "bltouch_probe_failure", "medium", ""),
        (
            "Failed to verify BLTouch probe is raised; retrying.",
            "bltouch_probe_failure",
            "medium",
            "",
        ),
        ("probe failed", "probe_failure", "medium", ""),
        (
            "Heater extruder not heating at expected rate",
            "heater_heating_failure",
            "high",
            "extruder",
        ),
        (
            "Transition to shutdown state: Heater heater_bed not heating at expected rate",
            "heater_heating_failure",
            "high",
            "heater_bed",
        ),
        ("No trigger on probe after full movement", "homing_no_trigger", "high", "probe"),
        ("No trigger on stepper_x after full movement", "homing_no_trigger", "high", "stepper_x"),
        (
            "Endstop stepper_z still triggered after retract",
            "homing_endstop_still_triggered",
            "high",
            "stepper_z",
        ),
        (
            "TMC 'stepper_x' reports error: DRV_STATUS: 00010000 ot=1",
            "tmc_driver_fault",
            "high",
            "stepper_x",
        ),
        (
            'TMC "extruder_stepper secondary" reports error: GSTAT: 00000001 reset=1',
            "tmc_driver_fault",
            "high",
            "extruder_stepper secondary",
        ),
        (
            "Unable to read tmc uart 'stepper_y' register IFCNT",
            "tmc_communication_failure",
            "high",
            "stepper_y",
        ),
        (
            "Unable to write tmc uart 'extruder' register GCONF",
            "tmc_communication_failure",
            "high",
            "extruder",
        ),
        (
            "Unable to write tmc spi 'stepper_z' register CHOPCONF",
            "tmc_communication_failure",
            "high",
            "stepper_z",
        ),
        ("MCU Protocol error", "mcu_protocol_mismatch", "high", ""),
        (
            "msgproto.error: Command format mismatch: query_adxl345 oid=%c vs query_adxl345 oid=%c clock=%u",
            "mcu_protocol_mismatch",
            "high",
            "",
        ),
        ("!! Move out of range: 310.000 20.000 5.000 [0.000]", "move_out_of_range", "medium", ""),
        ("ActiveState=failed", "systemd_service_failed", "critical", ""),
        ("Result=exit-code", "systemd_service_failed", "critical", ""),
        ("Result=signal", "systemd_service_failed", "critical", ""),
        ("Start request repeated too quickly", "systemd_service_failed", "critical", ""),
    ],
)
def test_reported_faults_keep_component_evidence_and_guidance(message, code, severity, component):
    findings = RuleEngine().analyze(
        [ArtifactInput(kind="klippy_log", label="supplied-klippy-excerpt", content="\n" + message)]
    )
    assert len(findings) == 1
    finding = findings[0]
    assert finding.code == code
    assert finding.severity == severity
    assert finding.source == "supplied-klippy-excerpt"
    assert finding.evidence == f"Collected excerpt line 2: {message}"
    assert finding.proposed_fix
    if component:
        assert f"Reported component: {component}." in finding.summary


@pytest.mark.parametrize(
    "message",
    [
        "FileNotFoundError: [Errno 2] No such file or directory: '/dev/serial/by-id/printer'",
        "No such file or directory: '/tmp/camera.sock'",
        "Heater extruder within range of 210.000",
        "Starting heater checks for heater_bed",
        "TMC 'stepper_x' reports GSTAT: 00000000",
        "DRV_STATUS: 00000000 ot=0 otpw=0",
        "probe: TRIGGERED",
        "Endstop stepper_x: open",
        "Protocol error: websocket disconnected",
        "Unknown command: M600",
        "Loaded MCU 'mcu' 128 commands (v0.13.0)",
        "ActiveState=active\nResult=success",
        "# Heater extruder not heating at expected rate",
        "; No trigger on probe after full movement",
        "  # Timer too close",
    ],
)
def test_normal_unrelated_and_commented_messages_do_not_report_faults(message):
    assert RuleEngine().analyze([ArtifactInput(kind="klippy_log", content=message)]) == []


def test_config_text_and_logged_config_dumps_do_not_become_runtime_faults():
    message = "Heater extruder not heating at expected rate"
    content = (
        "===== Config file =====\n"
        "[gcode_macro EXAMPLE]\n"
        f'  RESPOND MSG="{message}"\n'
        "\n=======================\n"
        "# No trigger on probe after full movement\n"
        f"{message}\n"
    )
    assert RuleEngine().analyze([ArtifactInput(kind="config_snippet", content=message)]) == []
    findings = RuleEngine().analyze([ArtifactInput(kind="klippy_log", content=content)])
    assert len(findings) == 1
    assert findings[0].evidence == f"Collected excerpt line 7: {message}"
    assert (
        RuleEngine().analyze([ArtifactInput(content="===== Config file =====\n" + message)]) == []
    )


def test_repeated_faults_are_deduplicated_without_hiding_other_components_or_sources():
    message = "Heater extruder not heating at expected rate"
    content = "\n".join(
        [message, message.upper(), "Heater heater_bed not heating at expected rate"]
    )
    findings = RuleEngine().analyze(
        [
            ArtifactInput(label="klippy.log", content=content),
            ArtifactInput(label="klippy.log", content=message),
            ArtifactInput(label="journalctl klipper", content=message),
        ]
    )
    assert len(findings) == 3
    assert sum("Reported component: extruder." in item.summary for item in findings) == 2
    assert any("Reported component: heater_bed." in item.summary for item in findings)
    assert findings[-1].source == "journalctl klipper"


def test_generic_probe_failure_does_not_assume_bltouch_hardware():
    finding = RuleEngine().analyze([ArtifactInput(content="Inductive probe failed")])[0]
    assert finding.code == "probe_failure"
    assert "BLTouch" not in finding.summary + finding.proposed_fix


def test_findings_are_sorted_by_severity_and_long_evidence_is_bounded_at_the_match():
    content = (
        "Move out of range: 310 20 5 [0]\n"
        + "x" * 2000
        + " Heater extruder not heating at expected rate "
        + "y" * 2000
        + "\nLost communication with MCU 'mcu'"
    )
    findings = RuleEngine().analyze([ArtifactInput(content=content)])
    assert [finding.severity for finding in findings] == ["critical", "high", "medium"]
    assert "Heater extruder not heating at expected rate" in findings[1].evidence
    assert len(findings[1].evidence) < 1200


def test_guidance_preserves_safety_checks_and_leaves_causes_unproven():
    messages = [
        "Heater heater_bed not heating at expected rate",
        "No trigger on probe after full movement",
        "TMC 'stepper_x' reports error: GSTAT: 00000001 reset=1",
        "MCU Protocol error",
        "Move out of range: 310 20 5 [0]",
    ]
    findings = {
        item.code: item
        for item in RuleEngine().analyze([ArtifactInput(content="\n".join(messages))])
    }
    assert "Do not disable verify_heater" in findings["heater_heating_failure"].proposed_fix
    assert "Do not extend travel limits" in findings["homing_no_trigger"].proposed_fix
    assert "register flags" in findings["tmc_driver_fault"].summary
    assert "compatibility needs verification" in findings["mcu_protocol_mismatch"].summary
    assert "verify physical clearance" in findings["move_out_of_range"].proposed_fix
