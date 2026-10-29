import pytest

from klipperai_agent.config.models import ConfigRequestTarget
from klipperai_agent.config.requests import ConfigPromptPayload
from klipperai_agent.config.templates.catalog import ProposalCatalog
from klipperai_agent.config.templates.features import feature_proposal
from klipperai_agent.profile.models import PrinterProfile
from tests.test_config_analysis import snapshot


def payload(feature, message, tree=None):
    return ConfigPromptPayload(
        message, tree or snapshot(), ConfigRequestTarget(feature, "test"), PrinterProfile()
    )


def test_parameterized_shaper_merges_measured_values_into_observed_file():
    tree = snapshot(
        (
            "tuning.cfg",
            "[input_shaper]\nshaper_type: mzv\nshaper_freq_x: 42\nshaper_freq_y: 50\ndamping_ratio_x: 0.1",
        )
    )
    proposal = ProposalCatalog().build(
        payload("input_shaper", "Use measured shaper_freq_x=43.2 shaper_freq_y=51.0", tree)
    )
    assert proposal.target_file == "tuning.cfg"
    assert "shaper_freq_x: 43.2" in proposal.config and "damping_ratio_x: 0.1" in proposal.config
    assert "shaper_type: mzv" in proposal.config
    assert "user-supplied" in " ".join(proposal.assumptions)
    missing = ProposalCatalog().build(payload("input_shaper", "shaper_freq_x: 40"))
    assert "<Y_FREQ>" in missing.config and "<X_SHAPER_TYPE>" in missing.config


@pytest.mark.parametrize(
    "feature,message,expected",
    [
        (
            "bed_mesh",
            "mesh_min=20, 25 mesh_max=200,200 probe_count=7,7 algorithm=bicubic",
            "mesh_min: 20, 25",
        ),
        (
            "probe",
            "samples=3 samples_result=median samples_tolerance=0.01 samples_tolerance_retries=3",
            "samples_tolerance: 0.01",
        ),
    ],
)
def test_probe_and_mesh_parameters_keep_unknown_geometry_unresolved(feature, message, expected):
    proposal = ProposalCatalog().build(payload(feature, message))
    assert expected in proposal.config
    if feature == "probe":
        assert "<PROBE_PIN>" in proposal.config and "<Z_OFFSET>" in proposal.config
    assert "No calibration has been performed" in " ".join(proposal.warnings)


def test_feature_generation_falls_back_on_ambiguity_and_offers_working_status_macro():
    warnings = []
    tree = snapshot(("printer.cfg", "[probe]\npin: PA1"), ("extra.cfg", "[probe]\npin: PA2"))
    assert feature_proposal(payload("probe", "samples=3", tree), warnings) is None
    assert "Multiple feature sections" in warnings[0]
    assert feature_proposal(payload("probe", "Make a probe"), []) is None
    assert feature_proposal(payload("fan", "pin=PA1"), []) is None
    macro = ProposalCatalog().build(payload("macro", "Create a printer status macro"))
    assert "action_respond_info" in macro.config and '"heater_bed" in printer' in macro.config
    assert "G28" not in macro.config and "M104" not in macro.config
    # Invalid/truncated existing evidence must not become a baseline for generated values.
    broken = snapshot(("printer.cfg", "[probe]\npin: PA1\npin: PA2"))
    assert "<PROBE_PIN>" in ProposalCatalog().build(payload("probe", "samples=3", broken)).config
