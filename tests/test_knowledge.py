from dataclasses import replace

import pytest
from pydantic import ValidationError

from klipperai_agent.domain.knowledge import ComponentIdentity, KnowledgeSetup
from klipperai_agent.domain.proposals import ConfigProposal
from klipperai_agent.knowledge.eddy import inspect_eddy
from klipperai_agent.knowledge.fans import inspect_fan_ports as inspect_ports
from klipperai_agent.knowledge.identity import component_status, profile_setup
from klipperai_agent.knowledge.pins import config_rows, pin_ownership
from klipperai_agent.knowledge.retrieval import search_documents
from klipperai_agent.knowledge.review import review_fan_hardware
from klipperai_agent.knowledge.sources import mapping_evidence
from tests.knowledge_helpers import documents, setup, snapshot


def proposal(config):
    return ConfigProposal(
        feature="fan",
        title="Additional fan",
        target_file="printer.cfg",
        config=config,
        rationale="Requested fan",
    )


def inspect_fan_ports(component, docs, changed, cfg):
    # Existing pin checks start with explicitly reviewed synthetic source evidence.
    return inspect_ports(
        component, docs, changed, cfg, setup().reviewed_fan_mappings.get(component.role, "")
    )


def test_identity_validation_exact_variants_and_document_states():
    seeded = profile_setup({"mainboard": "Manta E3EZ", "firmware_flavor": "Kalico"})
    assert seeded.components[0].model == "Manta E3EZ" and not seeded.components[0].confirmed
    assert (
        len(
            profile_setup({"mainboard": "x" * 300, "firmware_flavor": "x" * 300})
            .components[0]
            .model
        )
        == 120
    )
    assert (
        seeded.profile_signature
        == profile_setup({"mainboard": "Manta E3EZ", "firmware_flavor": "Kalico"}).profile_signature
    )
    with pytest.raises(ValidationError, match="only once"):
        KnowledgeSetup(components=[seeded.components[0], seeded.components[0]])
    with pytest.raises(ValidationError):
        ComponentIdentity(role="mainboard", mcu="../../printer.cfg")
    with pytest.raises(ValidationError):
        KnowledgeSetup(command="restart")
    component = setup().components[0]
    docs = documents()
    assert component_status(component, docs, False)["status"] == "Documentation cached"
    assert component_status(component, [], False)["status"] == "Documentation unavailable"
    assert component_status(component, docs, True)["status"] == "Needs details"
    assert (
        component_status(component.copy(update={"revision": "2.0"}), docs, False)["document_ids"]
        == []
    )
    unknown = ComponentIdentity(role="auxiliary", model="Any new board")
    assert len(component_status(unknown, [], False)["gaps"]) == 1
    assert component_status(ComponentIdentity(role="extra"), [], False)["status"] == "Needs details"
    with pytest.raises(ValidationError, match="reserved"):
        ComponentIdentity(role="all")
    signature = mapping_evidence(component, docs)["signature"]
    assert component_status(component, docs, False, signature)["fan_mappings_reviewed"]
    docs[0].digest = "changed"
    assert not component_status(component, docs, False, signature)["fan_mappings_reviewed"]


def test_pin_ownership_multiline_aliases_virtual_pins_and_all_users():
    cfg = snapshot(
        """
[board_pins fans]
aliases:
    FAN=PA8,
    FAN_ALIAS=FAN, RESERVED=<reserved>, PB14=<reserved>,
[board_pins th_fans]
mcu: th
aliases: COOL=PB15
[multi_pin group]
pins: PB15, th:COOL
[fan]
pin: !FAN_ALIAS
[controller_fan case]
pin: multi_pin:group
[temperature_fan exhaust]
pin: ^th:PA5
[stepper_z]
endstop_pin: probe:z_virtual_endstop
[stepper_x]
endstop_pin: tmc2209_stepper_x:virtual_endstop
[output_pin unused]
pin: None
[gcode_macro START_PRINT]
gcode:
    SET_FAN_SPEED FAN=case SPEED=1
""",
        notes=["Auto-detected root config file: printer.cfg"],
    )
    pins = pin_ownership(cfg)
    assert pins["gaps"] == []
    assert set(pins["owners"]) == {"mcu:PA8", "mcu:PB15", "mcu:PB14", "th:PB15", "th:PA5"}
    assert pins["owners"]["mcu:PA8"][0]["section"] == "fan"
    assert "SET_FAN_SPEED" in config_rows(cfg)[-1]["value"]
    assert pins["owners"]["mcu:PB14"][0]["section"] == "board_pins reservation"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("[board_pins test]\naliases: invalid", "alias could not"),
        ("[board_pins test]\naliases: A=PA8,A=PB15", "Conflicting"),
        ("[board_pins test]\naliases: A=B,B=A\n[fan]\npin: A", "Cyclic"),
        ("[fan]\npin: multi_pin:missing", "Unresolved multi_pin"),
        ("[fan]\npin: unknown:PA8", "Unresolved or reserved"),
        ("[fan]\npin: YOUR_PIN", "Unresolved or reserved"),
    ],
)
def test_incomplete_pin_evidence_blocks_free_claims(text, expected):
    cfg = snapshot(text)
    assert expected in str(pin_ownership(cfg)["gaps"])
    report = inspect_fan_ports(setup().components[0], documents(), False, cfg)
    assert report["gaps"] and all(
        item["pin"] is None and item["example"] is None for item in report["ports"]
    )


def test_fan_ports_distinguish_mcus_used_and_physically_unknown():
    cfg = snapshot("[fan]\npin: PA8\n[heater_fan hotend]\npin: th:PB15")
    main = inspect_fan_ports(setup().components[0], documents(), False, cfg)
    assert main["gaps"] == []
    assert main["ports"][0]["status"] == "in use" and main["ports"][0]["example"] is None
    assert main["ports"][1]["pin"] == "mcu:PB15"
    assert "physical occupancy unconfirmed" in main["ports"][1]["status"]
    assert main["ports"][1]["example"] == "[fan_generic additional_fan]\npin: mcu:PB15\n"
    th = inspect_fan_ports(setup().components[1], documents(), False, cfg)
    assert th["ports"][1]["status"] == "in use" and th["ports"][0]["pin"] == "th:PA9"
    assert "Saved connection conflicts" in str(
        inspect_fan_ports(
            setup().components[1].copy(update={"connection": "USB"}), documents(), False, cfg
        )
    )
    assert "active serial" in str(
        inspect_fan_ports(
            setup().components[0].copy(update={"connection": "CAN"}), documents(), False, cfg
        )
    )
    assert "absent" in str(
        inspect_fan_ports(
            setup().components[0].copy(update={"mcu": "missing"}), documents(), False, cfg
        )
    )
    assert "Build knowledge" in str(inspect_fan_ports(setup().components[0], [], False, cfg))
    unknown = inspect_fan_ports(ComponentIdentity(role="mainboard"), [], False, cfg)
    assert unknown["ports"] == [] and unknown["sources"] == []
    assert pin_ownership(replace(cfg, documents=[]))["gaps"]
    assert pin_ownership(snapshot(truncated=True))["gaps"]
    assert pin_ownership(snapshot(notes=["Include pattern matched no files: gone.cfg"]))["gaps"]
    assert not pin_ownership(
        snapshot(notes=["Config content truncated after the opening excerpt: printer.cfg"])
    )["gaps"]


def test_bus_reservations_include_defaults_without_blocking_other_mcus():
    cfg = snapshot("[probe_eddy_current btt]\ni2c_mcu: eddy\n[adxl345]\ncs_pin: th:PA4")
    report = inspect_fan_ports(setup().components[0], documents(), False, cfg)
    assert report["gaps"] == []  # Eddy I2C and toolhead SPI cannot occupy a mainboard pin.
    th = inspect_fan_ports(setup().components[1], documents(), False, cfg)
    assert "Hardware bus" in str(th["gaps"]) and all(port["pin"] is None for port in th["ports"])
    unknown = inspect_fan_ports(
        setup().components[0], documents(), False, snapshot("[adxl345]\nspi_bus: spi1")
    )
    assert "Hardware bus" in str(unknown["gaps"])
    software = inspect_fan_ports(
        setup().components[1],
        documents(),
        False,
        snapshot(
            "[adxl345]\ncs_pin: th:PA4\nspi_software_sclk_pin: th:PA5\nspi_software_mosi_pin: th:PA7\nspi_software_miso_pin: th:PA6"
        ),
    )
    assert software["gaps"] == [] and software["ports"][3]["status"] == "in use"


def test_unnamed_alias_sections_extensions_and_reserved_fan_outputs():
    cfg = snapshot(
        "[board_pins]\naliases: FAN=PA8\naliases_extra: PB15=<reserved>, F2=PB14\n[fan]\npin: FAN\n[fan_generic case]\npin: F2"
    )
    report = inspect_fan_ports(setup().components[0], documents(), False, cfg)
    assert not report["gaps"]
    assert all(port["status"] == "in use" and port["example"] is None for port in report["ports"])


def test_fan_proposal_review_rejects_wrong_pins_and_double_allocation():
    data, docs = setup(), documents()
    cfg = snapshot("[fan]\npin: PA8")

    def check(text, **kw):
        return review_fan_hardware(
            proposal(text), kw.get("cfg", cfg), kw.get("data", data), docs, kw.get("changed", False)
        )

    assert check("[fan_generic extra]\npin: PB15") == []
    assert "not verified" in str(check("[fan_generic extra]\npin: PB15\n[adxl345]\ncs_pin: PA4"))
    assert check("[fan]\npin: PA8") == []  # Editing the existing section.
    assert check("[bed_mesh]\nmesh_min: 10,10") == []
    assert "complete" in str(
        check("[fan_generic one]\npin: PB15\n[fan_generic missing]\nmax_power: 0.5")
    )
    assert "already used" in str(check("[fan_generic extra]\nPIN: PA8"))
    assert "already used" in str(check("[fan_generic extra]\npin: PA8"))
    assert "already used" in str(
        check("[fan_generic one]\npin: PB15\n[fan_generic two]\npin: PB15")
    )
    assert "not verified" in str(check("[fan_generic extra]\npin: PA9"))
    assert "not verified" in str(check("[fan_generic extra]\npin: PB15", changed=True))
    assert "could not be resolved" in str(check("[fan_generic extra]\npin: not_a_pin"))
    assert "complete" in str(check("[fan_generic extra]\nmax_power: 1"))
    assert "one confirmed" in str(check("[fan_generic extra]\npin: PB15", data=KnowledgeSetup()))
    data.components[1].mcu = "mcu"
    assert "one confirmed" in str(check("[fan_generic extra]\npin: PB15"))


def test_local_retrieval_and_eddy_require_matching_firmware_evidence():
    docs = documents()
    passages = search_documents(docs, "calibration", {"eddy-guide", "klipper-eddy"})
    assert len(passages) == 2 and passages[0]["start_line"] == 1
    assert passages[0]["digest"] and passages[0]["fetched_at"]
    assert search_documents(docs, "xx", {"eddy-guide"}) == []
    docs[-1].content = "\n".join(["thermal drift"] * 150)
    assert len(search_documents(docs, "thermal", {"klipper-eddy"})) == 3
    report = inspect_eddy(
        setup(),
        docs,
        False,
        snapshot("""
[probe_eddy_current btt]
sensor_type: ldc1612
i2c_mcu: eddy
x_offset: 20
[temperature_probe btt]
sensor_type: Generic 3950
[bed_mesh]
mesh_min: 20,20
[gcode_macro START_PRINT]
gcode:
    BED_MESH_PROFILE LOAD=default
#*# calibrate = 1
#*# drift_calibration = 2
#*# calibration_temp = 25
"""),
        "bed mesh",
    )
    assert report["passages"] and len(report["saved_calibration_markers"]) == 3
    assert "not verified against" in str(report["gaps"])
    assert not any("unknown" in gap for gap in report["gaps"])
    assert any(row["value"] == "BED_MESH_PROFILE LOAD=default" for row in report["configuration"])
    missing = inspect_eddy(KnowledgeSetup(), [], False, replace(snapshot(), documents=[]), "height")
    assert len(missing["gaps"]) >= 5
    mismatched = inspect_eddy(
        setup(),
        docs,
        True,
        snapshot("[temperature_probe other]\nsensor_type: Generic 3950"),
        "drift",
    )
    assert "do not match" in str(mismatched["gaps"])


def test_eddy_detects_mcu_transport_and_missing_thermal_sections():
    data = setup()
    cfg = snapshot("[probe_eddy_current btt]\ni2c_mcu: th")
    data.components[2].connection = "CAN"
    report = inspect_eddy(data, documents(), False, cfg, "drift")
    assert "connection type conflicts" in str(report["gaps"])
    assert "differs from the saved Eddy MCU" in str(report["gaps"])
    assert "no matching temperature_probe" in str(report["gaps"])
    data.components[2].mcu = "absent"
    assert "absent from the active" in str(
        inspect_eddy(data, documents(), False, cfg, "drift")["gaps"]
    )
