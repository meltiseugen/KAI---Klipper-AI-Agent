"""Manual feature drafts use observed targets and keep calibration gaps explicit."""

import pytest

from klipperai_agent.config.review_parser import parse_review_config
from klipperai_agent.config.templates.catalog import ProposalCatalog
from tests.test_config_analysis import snapshot
from tests.test_config_features import payload


@pytest.mark.parametrize(
    "prompt,name,required",
    [
        ("Create a start print macro", "START_PRINT", "params.BED_TEMP"),
        ("Create an end print macro", "END_PRINT", "TURN_OFF_HEATERS"),
        ("Create a preflight macro", "KLIPPERAI_PREFLIGHT", "action_respond_info"),
    ],
)
def test_purpose_specific_macros_parse_and_remain_manual(prompt, name, required):
    proposal = ProposalCatalog().build(payload("macro", prompt))
    assert f"[gcode_macro {name}]" in proposal.config and required in proposal.config
    assert not parse_review_config(proposal.config)[1]
    assert "No printer command" in " ".join(proposal.warnings)
    if name == "START_PRINT":
        assert "BED_MESH_PROFILE" not in proposal.config and "G1 " not in proposal.config
        assert "action_raise_error" in proposal.config
    if name == "END_PRINT":
        assert "G1 " not in proposal.config and "M84" not in proposal.config


def test_macro_existing_target_and_ambiguous_sections_are_visible():
    tree = snapshot(("start.cfg", "[gcode_macro START_PRINT]\ngcode: M400"))
    proposal = ProposalCatalog().build(payload("macro", "Create START_PRINT macro", tree))
    assert proposal.target_file == "start.cfg"
    ambiguous = snapshot(
        ("a.cfg", "[gcode_macro END_PRINT]\ngcode: M400"),
        ("b.cfg", "[gcode_macro END_PRINT]\ngcode: M400"),
    )
    proposal = ProposalCatalog().build(payload("macro", "Create END_PRINT macro", ambiguous))
    assert "Multiple target" in " ".join(proposal.warnings)


def test_bltouch_uses_supplied_pins_and_retains_observed_options():
    tree = snapshot(
        (
            "probe.cfg",
            "[bltouch]\nsensor_pin: ^PA1\ncontrol_pin: PA2\nx_offset: 1\ny_offset: 2\nz_offset: 3\nsamples: 3",
        )
    )
    proposal = ProposalCatalog().build(payload("probe", "Generate BLTouch control_pin=PA4", tree))
    assert proposal.target_file == "probe.cfg"
    assert "sensor_pin: ^PA1" in proposal.config and "control_pin: PA4" in proposal.config
    assert "samples: 3" in proposal.config and "[probe]" not in proposal.config
    missing = ProposalCatalog().build(payload("probe", "Generate BLTouch"))
    assert "<SENSOR_PIN>" in missing.config and "<Z_OFFSET>" in missing.config
    broken = snapshot(("printer.cfg", "[bltouch]\nsensor_pin: PA1\nsensor_pin: PA2"))
    assert (
        "<SENSOR_PIN>"
        in ProposalCatalog().build(payload("probe", "Generate BLTouch", broken)).config
    )


@pytest.mark.parametrize("sensor", ["adxl345", "lis2dw"])
def test_resonance_templates_keep_unknown_mounting_and_measurement_geometry_explicit(sensor):
    proposal = ProposalCatalog().build(
        payload(
            "input_shaper",
            f"Generate {sensor} accelerometer cs_pin=th:PA4 spi_bus=spi1 axes_map=x,y,z probe_points=100,100,30",
        )
    )
    assert f"[{sensor}]" in proposal.config and "cs_pin: th:PA4" in proposal.config
    assert "[resonance_tester]" in proposal.config and "spi_bus: spi1" in proposal.config
    assert "shaper_freq" not in proposal.config
    assert not parse_review_config(proposal.config)[1]
    missing = ProposalCatalog().build(payload("input_shaper", f"Generate {sensor} accelerometer"))
    assert (
        "<CS_PIN>" in missing.config
        and "<SAFE_X>" in missing.config
        and "<AXES_MAP>" in missing.config
    )
