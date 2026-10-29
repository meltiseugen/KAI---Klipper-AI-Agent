from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from klipperai_agent.application.proposal_review import ProposalReviewService
from klipperai_agent.application.review_firmware import read_review_firmware
from klipperai_agent.config.collector import ConfigCollector
from klipperai_agent.config.option_review import review_options, value_problem
from klipperai_agent.config.option_rules import OptionRule
from klipperai_agent.config.review import ProposalReviewer
from klipperai_agent.config.review_parser import parse_review_config
from klipperai_agent.domain.investigation import InvestigationResult
from klipperai_agent.domain.proposals import ReviewFirmware
from klipperai_agent.profile.models import PrinterProfile
from tests.test_proposal_review import proposal


@pytest.fixture
def config_tree(tmp_path):
    root = tmp_path / "config"
    root.mkdir()
    (root / "printer.cfg").write_text(
        "[fan]\npin: PA1\nmax_power: 0.8\n"
        "[heater_bed]\nheater_pin: PB1\nsensor_type: Generic 3950\nsensor_pin: PA2\n"
        "min_temp: 0\nmax_temp: 120\ncontrol: pid\npid_Kp: 20\npid_Ki: 1\npid_Kd: 70\n"
        "[gcode_macro EXISTING]\ngcode:\n  M117 existing\n",
        encoding="utf-8",
    )
    return ConfigCollector(tmp_path)


def review(config_tree, text, **kwargs):
    return (
        ProposalReviewer()
        .review(
            proposal(config=text, target_file="printer.cfg"),
            config_tree.collect(),
            **kwargs,
        )
        .review
    )


def codes(result, severity=None):
    return {check.code for check in result.checks if severity is None or check.severity == severity}


@pytest.mark.parametrize(
    "text,code",
    [
        ("[fan]\nmax_power: 1.1", "option_value"),
        ("[fan]\nmax_power: 0", "option_value"),
        ("[fan]\nmax_power: nan", "option_value"),
        ("[fan]\ncycle_time: inf", "option_value"),
        ("[fan]\nhardware_pwm: maybe", "option_value"),
        ("[fan]\ntachometer_ppr: 2.5", "option_value"),
        ("[fan]\noff_below: -0.1", "option_value"),
        ("[heater_bed]\nmin_temp: 130", "option_order"),
        ("[heater_bed]\nmin_temp: 120", "option_order"),
        ("[fan_generic new]\nmax_power: 0.5", "required_option"),
        ("[heater_generic new]\ncontrol: pid", "pid_coefficients"),
        ("[input_shaper]\nshaper_type: unsupported", "option_value"),
        ("[bed_mesh]\nprobe_count: 1, 3", "option_value"),
        ("[bed_mesh]\nmesh_min: 100, 20\nmesh_max: 10, 100", "mesh_bounds"),
        ("[stepper_x]\nposition_min: 200\nposition_max: 0", "option_order"),
        ("[temperature_fan hot]\nmin_speed: 0.8\nmax_speed: 0.2", "option_order"),
        ("[fan]\nmax_power: 0.8\nmax_power: 0.9", "config_syntax"),
    ],
)
def test_invalid_proposed_values_and_merged_relationships(config_tree, text, code):
    result = review(config_tree, text)
    assert result.status == "needs_information"
    assert code in codes(result, "error")
    assert result.mode == "manual_only"


def test_partial_merge_retains_required_options_and_pid_coefficients(config_tree):
    result = review(config_tree, "[heater_bed]\nmax_temp: 110\ncontrol: pid")
    assert result.status == "manual_review"
    assert "PID control needs" not in str(result.errors)
    assert "max_temp" in result.checks[0].option
    assert result.checks[0].line == 2
    assert result.firmware.source == "unavailable"
    assert any("No exact" in warning for warning in result.warnings)
    assert any("thermal protection" in step for step in result.manual_steps)
    assert any("Back up" in step for step in result.manual_steps)


def test_unknown_extensions_and_expressions_are_unverified_not_invalid(config_tree):
    result = review(
        config_tree,
        "[fan]\ncustom_setting: 4\nmax_power: {printer.custom.value}\n"
        "[vendor_probe scanner]\nunknown_pin: PA4\n"
        "[gcode_macro EXISTING]\nvariable_custom: {'a': 1}\n",
    )
    assert result.status == "manual_review"
    assert {
        "option_unverified",
        "section_unverified",
        "value_unverified",
        "macro_variable",
    } <= codes(result)
    assert any("Read every macro/Jinja" in step for step in result.manual_steps)


def test_macro_multiline_comments_equals_and_header_comments(config_tree):
    text = (
        "[gcode_macro TEST] # comment\n"
        "description = Labels: ready\n"
        "gcode:\n"
        "  {% if params.VALUE|default(0)|int %}\n"
        "    M117 pin: PA1\n"
        "    [not_a_section]\n"
        "  {% endif %}\n\n"
        "[fan] ; comment\nmax_power = 0.5#comment\n"
    )
    result = review(config_tree, text)
    assert result.status == "manual_review"
    assert len([check for check in result.checks if check.code == "option_value"]) == 1
    assert next(check for check in result.checks if check.option == "max_power").line == 10
    parsed, errors = parse_review_config(text)
    assert not errors and [item.name for item in parsed] == ["gcode_macro TEST", "fan"]
    assert "pin: PA1" in parsed[0].values["gcode"]
    assert not parse_review_config("[include extra.cfg]")[0]
    assert parse_review_config("[DEFAULT]\nmax_power: 0.5\n[fan]\npin: PA1")[1]
    assert parse_review_config("[ ]\nmax_power: 0.5")[1]
    parsed, errors = parse_review_config("[DEFAULT]\n[fan]\npin: PA1\nmax_power: 0.5")
    assert not errors and parsed[0].lines["max_power"] == 4


@pytest.mark.parametrize(
    "value,rule,valid",
    [
        ("1", OptionRule("boolean"), True),
        ("YES", OptionRule("boolean"), True),
        ("", OptionRule("boolean"), False),
        ("0,0", OptionRule("pair"), True),
        ("1,2,3", OptionRule("pair"), False),
        ("3", OptionRule("integer_pair", minimum=3), True),
        ("3,4", OptionRule("integer_pair", minimum=3), True),
        ("3,x", OptionRule("integer_pair", minimum=3), False),
        ("1", OptionRule("number", maximum=1, below=True), False),
        ("1", OptionRule("number", maximum=1), True),
        ("0", OptionRule("number", minimum=0), True),
        ("not-a-number", OptionRule("number"), False),
        ("unknown", OptionRule(), True),
    ],
)
def test_numeric_boundaries_and_supported_value_forms(value, rule, valid):
    assert (not value_problem(value, rule)) is valid


@pytest.mark.parametrize(
    "version,flavor,text,severity",
    [
        ("v0.12.0", "Klipper", "[printer]\nminimum_cruise_ratio: 0.5", "error"),
        ("v0.13.0", "Klipper", "[printer]\nminimum_cruise_ratio: 0.5", None),
        ("v0.13.0-0-gabcdef", "Klipper", "[bed_mesh]\nrelative_reference_index: 3", "error"),
        ("v0.12.0", "Klipper", "[bed_mesh]\nrelative_reference_index: 3", None),
        ("v0.13.0", "Klipper", "[printer]\nmax_accel_to_decel: 1000", "warning"),
        ("v0.12.0", "Klipper", "[printer]\nmax_accel_to_decel: 1000", None),
        ("v0.13.0-100-gabc", "Klipper", "[printer]\nmax_accel_to_decel: 1000", "warning"),
        ("v0.13.0-dirty", "Klipper", "[output_pin led]\nstatic_value: 1\npin: PA2", "warning"),
        ("v0.13.0", "Klipper", "[output_pin led]\nstatic_value: 1\npin: PA2", "error"),
        ("v0.13.0", "Kalico", "[printer]\nminimum_cruise_ratio: 0.5", "warning"),
        ("future", "Custom", "[printer]\nminimum_cruise_ratio: 0.5", "warning"),
    ],
)
def test_exact_release_checks_do_not_guess_git_or_fork_compatibility(
    config_tree, version, flavor, text, severity
):
    result = review(config_tree, text, firmware=ReviewFirmware(flavor=flavor, version=version))
    checks = [check for check in result.checks if check.code == "option_version"]
    assert ([check.severity for check in checks] or [None]) == [severity]
    if checks:
        assert checks[0].source_url.endswith("Config_Changes.html")


@pytest.mark.parametrize("mode", ["pid_v", "mpc", "dual_loop_pid"])
def test_kalico_heater_modes_are_not_rejected_as_unknown_values(config_tree, mode):
    text = f"[heater_bed]\ncontrol: {mode}"
    kalico = review(config_tree, text, firmware=ReviewFirmware(flavor="Kalico", version="abc"))
    assert kalico.status == "manual_review"
    assert "fork_control" in codes(kalico, "warning")
    klipper = review(
        config_tree, text, firmware=ReviewFirmware(flavor="Klipper", version="v0.13.0")
    )
    assert klipper.status == "needs_information"
    assert "fork_control" in codes(klipper, "error")


def test_firmware_change_and_previously_stale_proposals_stay_stale(config_tree):
    old = ReviewFirmware(flavor="Klipper", version="v0.12.0")
    initial = review(config_tree, "[fan]\nmax_power: 0.6", firmware=old)
    updated = review(
        config_tree,
        "[fan]\nmax_power: 0.6",
        firmware=ReviewFirmware(flavor="Klipper", version="v0.13.0"),
        previous=initial,
    )
    assert updated.status == "stale"
    assert updated.proposal_id == initial.proposal_id
    reverted = review(config_tree, "[fan]\nmax_power: 0.6", firmware=old, previous=updated)
    assert reverted.status == "stale"
    unavailable = review(config_tree, "[fan]\nmax_power: 0.6", previous=initial)
    assert unavailable.status == "manual_review"
    assert any("No exact" in warning for warning in unavailable.warnings)


def test_losing_live_version_evidence_does_not_invent_a_firmware_change(config_tree):
    initial = review(
        config_tree,
        "[fan]\nmax_power: 0.6",
        firmware=ReviewFirmware(
            flavor="Klipper", version="v0.13.0", source="live_version_saved_flavor"
        ),
    )
    fallback = review(
        config_tree,
        "[fan]\nmax_power: 0.6",
        previous=initial,
        firmware=ReviewFirmware(flavor="Klipper", version="v0.12.0", source="saved_profile"),
    )
    assert fallback.status == "manual_review"
    assert fallback.baseline_firmware == initial.firmware
    assert any("could not be rechecked" in warning for warning in fallback.warnings)


@pytest.mark.asyncio
async def test_live_firmware_fallback_and_review_service_never_write_printer_files(config_tree):
    profile = PrinterProfile(firmware_flavor="Klipper", firmware_version="v0.12.0")
    printer = SimpleNamespace(
        get_printer_info=AsyncMock(return_value={"software_version": "v0.13.0"})
    )
    firmware = await read_review_firmware(printer, profile)
    assert firmware.source == "live_version_saved_flavor" and firmware.version == "v0.13.0"
    assert "saved profile" in firmware.note
    for value in [{}, {"software_version": 123}, {"software_version": ""}]:
        printer.get_printer_info.return_value = value
        fallback = await read_review_firmware(printer, profile)
        assert fallback.source == "saved_profile"
        assert fallback.version == "v0.12.0" and "unavailable" in fallback.note
    printer.get_printer_info.side_effect = RuntimeError("secret path /private/config")
    fallback = await read_review_firmware(printer, None)
    assert fallback.source == "unavailable" and "private" not in str(fallback)
    assert (await read_review_firmware(None, None)).source == "unavailable"
    printer.get_printer_info.side_effect = None
    printer.get_printer_info.return_value = {"software_version": "v0.13.0"}
    service = ProposalReviewService(config_tree, printer=printer, profile=profile)
    original = config_tree.collect().revision()
    result = InvestigationResult(
        config_proposals=[proposal(config="[bed_mesh]\nrelative_reference_index: 1")]
    )
    await service.review(result)
    assert result.config_proposals[0].review.status == "needs_information"
    assert result.config_proposals[0].review.firmware.version == "v0.13.0"
    assert config_tree.collect().revision() == original


def test_relationships_with_unparseable_or_equal_values_and_guidance(config_tree):
    result = review(
        config_tree,
        "[heater_bed]\nmin_temp: unknown\nmax_temp: 100\n[bed_mesh]\nmesh_min: a,b\nmesh_max: 10,20",
    )
    assert "option_order" not in codes(result) and "mesh_bounds" not in codes(result)
    result = review(
        config_tree,
        "[temperature_fan hot]\npin: PA5\nsensor_type: test\ncontrol: watermark\nmin_temp: 0\nmax_temp: 100\nmin_speed: 0.5\nmax_speed: 0.5",
    )
    assert result.status == "manual_review"
    assert any("fan voltage" in item for item in result.manual_steps)
    result = review(
        config_tree,
        "[input_shaper]\nshaper_freq_x: 40\n[bltouch]\nsensor_pin: PA7\ncontrol_pin: PA8\nz_offset: 1\n[extruder1]\nrotation_distance: 22\n[stepper_z1]\nmicrosteps: 16",
    )
    assert any("resonance" in item for item in result.manual_steps)
    assert any("mesh edge" in item for item in result.manual_steps)
    # A malformed or clipped observed file cannot supply required missing values.
    snap = config_tree.collect()
    snap.documents[0].content = "[bad"
    parsed, _ = parse_review_config("[fan]\nmax_power: 0.5")
    checks = review_options(parsed, snap, "printer.cfg", ReviewFirmware())
    assert any(check.code == "required_option" for check in checks)
