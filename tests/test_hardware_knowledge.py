"""Synthetic bus sources and explicitly confirmed physical observations."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from klipperai_agent.agent.models import AgentLimits, ToolCall
from klipperai_agent.agent.registry import ToolRegistry
from klipperai_agent.agent.tools.components import ComponentArguments, ComponentDiagnosticTool
from klipperai_agent.application.knowledge_observations import (
    connector_observations,
    record_connector,
)
from klipperai_agent.domain.hardware import ConnectorObservation
from klipperai_agent.domain.knowledge import KnowledgeConflict
from klipperai_agent.knowledge.buses import (
    bus_evidence,
    connector_identity,
    extract_bus_mappings,
    resolved_ownership,
)
from klipperai_agent.knowledge.components import inspect_component
from klipperai_agent.knowledge.fans import inspect_fan_ports
from tests.knowledge_helpers import documents, setup, snapshot
from tests.test_agent import tool_context as tool_context


def bus_documents():
    docs = documents()
    docs[0].content += '\nDECL_CONSTANT_STR("BUS_PINS_spi1", "PA5,PA6,PA7");\nBUS_PINS_i2c1=PB6,PB7'
    return docs


def test_quoted_bus_pinmux_is_reviewed_and_bound_to_mcu_and_source():
    data, docs = setup(), bus_documents()
    component = data.components[0]
    evidence = bus_evidence(component, docs)
    assert {item["bus"] for item in evidence["candidates"]} == {"spi1", "i2c1"}
    assert extract_bus_mappings("BUS_PINS_bad=unknown,shell") == []
    cfg = snapshot(
        "[adxl345]\ncs_pin: PA4\nspi_bus: spi1\n[temperature_sensor chip]\ni2c_bus: i2c1"
    )
    unresolved = resolved_ownership(cfg, component, docs)
    assert all(not bus["resolved"] for bus in unresolved["buses"])
    resolved = resolved_ownership(cfg, component, docs, evidence["signature"])
    assert all(bus["resolved"] for bus in resolved["buses"])
    assert resolved["owners"]["mcu:PA5"][0]["bus_reservation"]
    assert resolved["owners"]["mcu:PB6"][0]["option"] == "i2c_bus"
    assert not resolved_ownership(
        cfg, component.copy(update={"mcu": "th"}), docs, evidence["signature"]
    )["buses"][0]["resolved"]
    docs[0].content += "\nBUS_PINS_spi1=PB1,PB2,PB3"
    assert bus_evidence(component, docs)["conflicts"] == ["spi1"]
    assert not resolved_ownership(cfg, component, docs, evidence["signature"])["buses"][0][
        "resolved"
    ]


def observation(**updates):
    values = dict(role="mainboard", connector="FAN1", occupancy="free", confirmed=True)
    values.update(updates)
    return ConnectorObservation(**values)


@pytest.mark.parametrize(
    "updates", [dict(confirmed=False), dict(occupancy="occupied"), dict(electrical_confirmed=True)]
)
def test_physical_records_require_explicit_confirmation_and_details(updates):
    with pytest.raises(ValidationError):
        observation(**updates)


def test_inventory_is_dated_identity_scoped_and_changes_fan_availability():
    data, docs = setup(), documents()
    data = record_connector(
        data,
        observation(
            occupancy="occupied",
            attached_device="Exhaust fan",
            electrical_confirmed=True,
            electrical_notes="24 V; verify current rating",
        ),
    )
    item = data.connectors[0]
    assert item.observed_at and item.identity_signature == connector_identity(data.components[0])
    report = inspect_fan_ports(
        data.components[0],
        docs,
        False,
        snapshot(),
        data.reviewed_fan_mappings["mainboard"],
        inventory=data.connectors,
    )
    fan = next(port for port in report["ports"] if port["connector"] == "FAN1")
    assert (
        fan["status"] == "in use" and fan["example"] is None and fan["electrical_verified_by_user"]
    )
    data = record_connector(data, observation())
    assert len(data.connectors) == 1 and data.connectors[0].occupancy == "free"
    free = inspect_fan_ports(
        data.components[0],
        docs,
        False,
        snapshot(),
        data.reviewed_fan_mappings["mainboard"],
        inventory=data.connectors,
    )
    assert (
        "user-confirmed free"
        in next(port for port in free["ports"] if port["connector"] == "FAN1")["status"]
    )
    changed = data.components[0].copy(update={"revision": "2"})
    assert connector_observations(data, changed)[0]["stale"]
    stale = inspect_fan_ports(changed, docs, False, snapshot(), inventory=data.connectors)
    assert all(
        port["physical_observation_stale"]
        for port in stale["ports"]
        if port["physical_observation"]
    )
    with pytest.raises(KnowledgeConflict):
        record_connector(data, observation(role="missing"))
    data.connectors = [observation(connector=str(index)) for index in range(64)]
    with pytest.raises(KnowledgeConflict, match="limit"):
        record_connector(data, observation(connector="new"))


@pytest.mark.parametrize(
    "family,section",
    [
        ("accelerometer", "adxl345"),
        ("probe", "probe"),
        ("driver", "tmc2209 stepper_x"),
        ("temperature", "temperature_sensor chamber"),
        ("filament", "filament_motion_sensor runout"),
    ],
)
def test_fixed_families_report_config_sources_and_missing_evidence(family, section):
    data, docs = setup(), bus_documents()
    report = inspect_component(
        data, docs, data.components[0], family, snapshot(f"[{section}]\npin: PA1"), False
    )
    assert report["configuration"][0]["section"] == section
    assert report["manual_checks"] and report["config_revision"]
    missing = inspect_component(data, docs, data.components[0], family, snapshot(), True)
    assert any("Confirm" in gap for gap in missing["gaps"])
    assert any("No supported" in gap for gap in missing["gaps"])


@pytest.mark.asyncio
async def test_component_tool_uses_fixed_objects_and_rejects_model_writes(tool_context):
    data, docs = setup(), bus_documents()
    knowledge = SimpleNamespace(read=AsyncMock(return_value=(data, docs, False)))
    tool = ComponentDiagnosticTool(knowledge)
    tool_context.snapshots[False] = snapshot("[adxl345]\ncs_pin: PA4\nspi_bus: spi1")
    tool_context.moonraker.list_printer_objects.return_value = ["adxl345", "toolhead", "arbitrary"]
    result = await tool.execute(
        ComponentArguments(role="mainboard", family="accelerometer"), tool_context
    )
    assert result["buses"] and any("unresolved" in gap for gap in result["gaps"])
    tool_context.moonraker.query_printer_objects.assert_awaited_with({"adxl345": None})
    assert tool_context.citations[0].line_basis == "file"
    missing = await tool.execute(ComponentArguments(role="missing", family="driver"), tool_context)
    assert "error" in missing
    tool_context.moonraker.list_printer_objects.return_value = []
    assert any(
        "No supported live" in gap
        for gap in (
            await tool.execute(ComponentArguments(role="mainboard", family="probe"), tool_context)
        )["gaps"]
    )
    tool_context.moonraker.list_printer_objects.side_effect = RuntimeError("private")
    assert any(
        "unavailable" in gap
        for gap in (
            await tool.execute(ComponentArguments(role="mainboard", family="probe"), tool_context)
        )["gaps"]
    )
    registry = ToolRegistry([tool], AgentLimits())
    assert "error" in await registry.execute(
        ToolCall("bad", tool.name, '{"role":"mainboard","family":"shell","command":"restart"}'),
        tool_context,
    )
