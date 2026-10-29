from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from klipperai_agent.agent.models import AgentLimits
from klipperai_agent.agent.tools.base import ToolArguments
from klipperai_agent.agent.tools.config_analysis import AnalyzeConfigTool, collect_analysis
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.config.analysis import analyze_config
from klipperai_agent.config.collector import ConfigCollector
from klipperai_agent.config.models import ConfigDocument, ConfigSnapshot
from klipperai_agent.config.parser import ConfigParser
from klipperai_agent.contracts.api import ChatRequest
from tests.test_agent import ScriptedModel, answer, call
from tests.test_agent import tool_context as tool_context
from tests.test_agent_integration import agent_service as agent_service
from tests.test_embedded_experience import embedded_client as embedded_client


def snapshot(*contents, notes=()):
    docs = [
        ConfigDocument(path, content, ConfigParser.extract_sections(content))
        for path, content in contents
    ]
    return ConfigSnapshot(docs[0].path if docs else None, docs, notes=list(notes))


def test_analysis_distinguishes_missing_globs_overrides_cycles_and_pins():
    tree = snapshot(
        (
            "printer.cfg",
            """[mcu]
serial: /dev/example
[include missing.cfg]
[include optional/*.cfg]
[include extras.cfg] # include comments
[safe_z_home]
home_xy_position: 1,1
[fan]
pin: ! PA1
[heater_fan cooling]
pin: PA1
[temperature_sensor aux]
sensor_pin: toolhead:PA2
[output_pin bad]
pin: !!PA4
[board_pins test]
aliases: FAN=PA1, LOOP=LOOP
[gcode_macro EXAMPLE]
variable_pin: text not a pin
gcode: M117 hello
""",
        ),
        (
            "extras.cfg",
            """[include printer.cfg]
[homing_override]
gcode: G28
[fan]
max_power: 0.5
[output_pin alias]
pin: FAN
[probe]
pin: LOOP
[stepper_z]
endstop_pin: probe:z_virtual_endstop
""",
        ),
    )
    report = analyze_config(tree)
    codes = {item.code for item in report.findings}
    assert {
        "missing_include",
        "empty_include_glob",
        "include_cycle",
        "section_override",
        "conflicting_homing",
        "shared_pin",
        "invalid_pin",
        "unknown_pin_chip",
    } <= codes
    assert (
        next(item for item in report.findings if item.code == "empty_include_glob").severity
        == "medium"
    )
    assert any("Cyclic" in note for note in report.notes)
    assert all(citation.line_number for citation in report.citations)
    assert "gcode_macro EXAMPLE" not in " ".join(item.evidence for item in report.findings)
    assert report.revision == tree.revision()


def test_analysis_incomplete_syntax_limits_and_empty():
    assert not analyze_config(snapshot()).complete
    broken = snapshot(
        ("printer.cfg", "[broken\n[fan]\npin: PA1"), notes=["Could not read an include"]
    )
    broken.documents[0].truncated = True
    report = analyze_config(broken)
    assert not report.complete and report.findings[0].code == "config_syntax"
    assert any("Incomplete file" in note for note in report.notes)
    many = snapshot(("printer.cfg", "\n".join(f"[include missing{i}.cfg]" for i in range(85))))
    report = analyze_config(many)
    assert len(report.findings) == 80 and not report.complete
    assert any("limited to 80" in note for note in report.notes)
    clean = analyze_config(snapshot(("printer.cfg", "[mcu]\nserial: example\n[fan]\npin: PA1")))
    assert clean.complete and not clean.findings
    virtual = analyze_config(
        snapshot(("printer.cfg", "[stepper_z]\nendstop_pin: probe:z_virtual_endstop"))
    )
    assert any(item.code == "missing_virtual_probe" for item in virtual.findings)


def test_collector_matches_firmware_globs_and_commented_headers(tmp_path):
    config = tmp_path / "config"
    (config / "extras/sub/deep").mkdir(parents=True)
    (config / "printer.cfg").write_text(
        "[include extras/**/*.cfg] # firmware glob\n[printer] # header\nkinematics: cartesian"
    )
    (config / "extras/sub/fan.cfg").write_text(
        "[fan] # part cooling\npin: PA1\n[respond] # next section"
    )
    (config / "extras/sub/deep/unused.cfg").write_text("[output_pin inactive]\npin: PA2")
    tree = ConfigCollector(tmp_path).collect()
    assert {doc.path for doc in tree.documents} == {"printer.cfg", "extras/sub/fan.cfg"}
    assert "fan" in tree.section_names
    fan = next(location for location in tree.section_locations if location.section == "fan")
    assert "[respond]" not in tree.section_block(fan)


@pytest.mark.asyncio
async def test_analysis_expands_active_only_and_handles_read_failures(tmp_path):
    directory = tmp_path / "config"
    directory.mkdir()
    (directory / "printer.cfg").write_text(
        "[mcu]\nserial: test\n" + "# comment\n" * 20 + "[fan]\npin: !!PA1"
    )
    (directory / "inactive.cfg").write_text("[fan]\npin: PA3")
    reader = ConfigCollector(tmp_path, max_chars_per_document=30)
    report = await collect_analysis(reader, reader.collect())
    assert report.files_checked == 1 and report.complete
    assert any(f.code == "invalid_pin" for f in report.findings)
    stale = reader.collect()
    (directory / "printer.cfg").write_text("[fan]\npin: PA2")
    report = await collect_analysis(reader, stale)
    assert not report.complete
    large = snapshot(("printer.cfg", "x" * 2_000_001))
    report = await collect_analysis(reader, large)
    assert not report.complete and report.files_checked == 0
    failing = SimpleNamespace(read_collected_document=Mock(side_effect=OSError()))
    assert not (await collect_analysis(failing, stale)).complete


@pytest.mark.asyncio
async def test_analysis_tool_registry_and_model_observation(tool_context):
    tool = AnalyzeConfigTool()
    with pytest.raises(ValueError):
        tool.arguments_type.parse_obj({"path": "../../secret"})
    result = await tool.execute(ToolArguments(), tool_context)
    assert result["files_checked"] == 1 and "revision" in result
    model = ScriptedModel(call("analyze_config"), answer())
    result = await AgentWorkflow(model, tool_context.moonraker, AgentLimits()).ainvoke(
        {"user_message": "Inspect my configuration"}, context=tool_context.services
    )
    assert result["agent_status"] == "completed"
    assert "Static analysis of active files" in str(model.conversations[-1])


@pytest.mark.asyncio
async def test_static_report_is_information_and_chat_still_uses_agent(agent_service, tmp_path):
    context = agent_service.workflow_context
    context.config_collector = ConfigCollector(tmp_path)
    context.intent_router = SimpleNamespace(
        classify=AsyncMock(side_effect=AssertionError("No provider call"))
    )
    response = await agent_service.chat(
        ChatRequest(
            session_id=agent_service.sessions.create().session_id, message="Analyze active config"
        )
    )
    assert response.response == "Your saved firmware is Kalico."
    assert any(event.tool == "get_printer_profile" for event in response.agent_events)
    context.intent_router.classify.assert_not_called()


def test_http_audit_requires_provider_and_valid_session(embedded_client, agent_service, tmp_path):
    agent_service.workflow_context.config_collector = ConfigCollector(tmp_path)
    client, session, _ = embedded_client
    for endpoint in ("chat", "chat/stream"):
        response = client.post(
            f"/printer/api/{endpoint}",
            json={"session_id": session, "message": "Audit active configuration"},
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "provider_not_configured"
        denied = client.post(
            f"/printer/api/{endpoint}",
            json={"session_id": "expired", "message": "Audit active configuration"},
        )
        assert denied.status_code == 403
