from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from test_agent import ScriptedModel, answer, call
from test_agent import tool_context as tool_context  # Shared read-only fixture.
from test_investigations import persistent_service as persistent_service

from klipperai_agent.agent.context_budget import fit_result
from klipperai_agent.agent.models import AgentLimits, ToolCall
from klipperai_agent.agent.registry import ToolRegistry
from klipperai_agent.agent.tools.config import InspectConfigTool, ReadConfigTool
from klipperai_agent.agent.tools.config_search import SearchConfigTool
from klipperai_agent.agent.tools.diagnostics import ReadDiagnosticTool
from klipperai_agent.agent.tools.objects import PrinterObjectsTool
from klipperai_agent.agent.tools.printer import DiagnosticsArguments, DiagnosticsTool
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.config.collector import ConfigCollector
from klipperai_agent.config.models import ConfigDocument, ConfigSnapshot
from klipperai_agent.contracts.api import ChatRequest
from klipperai_agent.diagnostics.models import DiagnosticsSnapshot
from klipperai_agent.domain.evidence import ArtifactInput
from klipperai_agent.domain.investigation import Evidence, InvestigationRequest


@pytest.mark.asyncio
async def test_modes_preload_exact_context_and_debug_reuses_its_reads(tool_context, tmp_path):
    (tmp_path / "config/printer.cfg").write_text(
        "[include macros.cfg]\n[printer]\nkinematics: corexy\n"
    )
    (tmp_path / "config/macros.cfg").write_text("[gcode_macro START_PRINT]\ngcode: G28\n")
    history = "Earlier diagnostic answer"
    memory = Evidence(source="old:klippy", content="Old temperature error")
    model = ScriptedModel(answer())
    result = await AgentWorkflow(model, tool_context.moonraker, AgentLimits()).ainvoke(
        {
            "user_message": "Explain my printer",
            "conversation_context": history,
            "memory": [memory.model_dump()],
        },
        context=tool_context.services,
    )
    payload = json.loads(model.conversations[0][1]["content"])
    assert result["mode"] == "chat"
    assert payload["saved_profile"]["firmware_flavor"] == "Kalico"
    assert {doc["path"] for doc in payload["active_config"]["files"]} == {
        "printer.cfg",
        "macros.cfg",
    }
    assert "G28" in json.dumps(payload) and "OLD" not in json.dumps(payload)
    assert payload["recent_conversation"] == history
    assert payload["historical_evidence"][0]["freshness"].startswith("historical")
    assert "diagnostics" not in payload and "live_status" not in payload
    tool_context.services.collector.collect.assert_not_awaited()
    tool_context.moonraker.get_printer_info.assert_not_awaited()
    assert all(
        item["sent_to_model"] for item in result["context_included"] if item["status"] == "included"
    )

    model = ScriptedModel(
        call("collect_diagnostics", {"include_system": True}),
        call("get_printer_status", identifier="2"),
        answer(),
    )
    result = await AgentWorkflow(model, tool_context.moonraker, AgentLimits()).ainvoke(
        {"user_message": "Investigate shutdown", "mode": "debug"},
        context=tool_context.services,
    )
    payload = json.loads(model.conversations[0][1]["content"])
    assert result["mode"] == "debug"
    assert payload["live_status"]["printer_info"]["state"] == "ready"
    assert "Timer too close" in json.dumps(payload["diagnostics"])
    tool_context.services.collector.collect.assert_awaited_once_with(
        [], include_host_logs=True, include_host_system=True
    )
    tool_context.moonraker.get_printer_info.assert_awaited_once()


@pytest.mark.asyncio
async def test_large_and_truncated_configs_are_indexed_and_missing_files_are_visible(tool_context):
    docs = [
        ConfigDocument("large.cfg", "x" * 80000, ["gcode_macro BIG"]),
        ConfigDocument("excerpt.cfg", "[printer]\n", ["printer"], truncated=True),
        ConfigDocument("huge-index.cfg", "x" * 80000, ["x" * 80000]),
    ]
    tool_context.services.config_collector = SimpleNamespace(
        collect_with_options=Mock(return_value=ConfigSnapshot("large.cfg", docs))
    )
    model = ScriptedModel(answer())
    result = await AgentWorkflow(model, tool_context.moonraker, AgentLimits()).ainvoke(
        {"user_message": "Explain config"}, context=tool_context.services
    )
    files = json.loads(model.conversations[0][1]["content"])["active_config"]["files"]
    assert files[0] == {
        "path": "large.cfg",
        "sections": ["gcode_macro BIG"],
        "content_omitted": True,
    }
    assert files[1]["truncated"] and len(files) == 2
    receipts = {item["source"]: item for item in result["context_included"]}
    assert receipts["large.cfg"]["status"] == receipts["excerpt.cfg"]["status"] == "partial"
    assert (
        receipts["huge-index.cfg"]["status"] == "omitted"
        and not receipts["huge-index.cfg"]["sent_to_model"]
    )
    assert len(json.dumps(model.conversations[0])) < AgentLimits().max_context_chars


@pytest.mark.asyncio
async def test_missing_evidence_is_reported_and_does_not_stop_answer(tool_context, tmp_path):
    tool_context.services.config_collector = ConfigCollector(tmp_path / "missing")
    tool_context.services.collector.collect.return_value = DiagnosticsSnapshot(
        False, None, [], ["Host logs unavailable"]
    )
    tool_context.moonraker.get_printer_info.side_effect = RuntimeError("private host detail")
    model = ScriptedModel(answer("Missing printer evidence"))
    result = await AgentWorkflow(model, tool_context.moonraker, AgentLimits()).ainvoke(
        {"user_message": "help", "mode": "debug"}, context=tool_context.services
    )
    assert result["agent_status"] == "completed"
    unavailable = {
        item["source"] for item in result["context_included"] if item["status"] == "unavailable"
    }
    assert unavailable == {"Active configuration", "get_printer_status", "collect_diagnostics"}
    assert "private host detail" not in json.dumps(model.conversations)
    assert "Host logs unavailable" in json.dumps(model.conversations)


@pytest.mark.asyncio
async def test_small_context_and_preflight_timeout_keep_receipts_truthful(tool_context):
    model = ScriptedModel(answer())
    workflow = AgentWorkflow(model, tool_context.moonraker, AgentLimits(max_context_chars=1))
    result = await workflow.ainvoke(
        {"user_message": "help", "conversation_context": "old"}, context=tool_context.services
    )
    assert result["agent_status"] == "limited" and not model.conversations
    assert not any(item["sent_to_model"] for item in result["context_included"])

    tool_context.services.profile = SimpleNamespace(
        to_summary=Mock(return_value={"large": '\\"\u2603' * 10000})
    )
    model = ScriptedModel(answer())
    result = await AgentWorkflow(
        model, tool_context.moonraker, AgentLimits(max_context_chars=12000)
    ).ainvoke({"user_message": "help", "mode": "debug"}, context=tool_context.services)
    assert result["agent_status"] == "completed"
    assert len(json.dumps(model.conversations[0])) < 12000
    assert any(
        item["status"] == "partial" and "budget" in item["detail"]
        for item in result["context_included"]
    )

    async def slow(*args, **kwargs):
        await asyncio.sleep(10)

    tool_context.services.collector.collect.side_effect = slow
    model = ScriptedModel(answer())
    result = await AgentWorkflow(
        model, tool_context.moonraker, AgentLimits(run_timeout_seconds=0.01)
    ).ainvoke({"user_message": "help", "mode": "debug"}, context=tool_context.services)
    assert result["agent_status"] == "limited" and not model.conversations
    assert not any(item["sent_to_model"] for item in result["context_included"])


@pytest.mark.asyncio
async def test_new_tools_multistep_results_have_sources_and_bounded_allowlists(tool_context):
    tool_context.moonraker.list_printer_objects.return_value = [
        "fan",
        "fan_generic chamber",
        "gcode_macro MOVE",
        "untrusted_name",
    ]
    model = ScriptedModel(
        call("search_config", {"query": "pa1"}),
        call("read_diagnostic_artifact", {"artifact_id": "diagnostic-1", "line_count": 2}, "2"),
        call("get_printer_objects", {"group": "fans"}, "3"),
        answer(),
    )
    result = await AgentWorkflow(model, tool_context.moonraker, AgentLimits()).ainvoke(
        {"user_message": "debug fan", "mode": "debug"}, context=tool_context.services
    )
    assert result["agent_status"] == "completed"
    assert "Timer too close" in model.conversations[-1][-3]["output"]
    assert "step_pin: PA1" in json.dumps(model.conversations[-1])
    assert any(item["path"].startswith("diagnostic:") for item in result["source_citations"])
    tool_context.moonraker.query_printer_objects.assert_awaited_once_with(
        {"fan": None, "fan_generic chamber": None}
    )
    assert all(
        item["sent_to_model"] for item in result["context_included"] if item["phase"] == "tool"
    )


@pytest.mark.asyncio
async def test_tool_argument_rejection_missing_evidence_and_truncation(tool_context):
    registry = ToolRegistry(
        [SearchConfigTool(), ReadDiagnosticTool(), PrinterObjectsTool()], AgentLimits()
    )
    for name, args in [
        ("search_config", {"query": "x", "max_matches": True}),
        ("search_config", {"query": "x", "path": "../../secret"}),
        ("search_config", {"query": " "}),
        ("read_diagnostic_artifact", {"artifact_id": "../../secret"}),
        ("read_diagnostic_artifact", {"artifact_id": "d", "line_count": 121}),
        ("read_diagnostic_artifact", {"artifact_id": "d", "start_line": "1"}),
        ("get_printer_objects", {"group": "gcode_macro MOVE"}),
        ("get_printer_objects", {"group": "fans", "command": "G28"}),
        ("get_printer_objects", {"group": "fans"}),
    ]:
        assert "error" in await registry.execute(
            ToolCall("1", name, json.dumps(args)), tool_context
        )
    result = await registry.execute(
        ToolCall(
            "1", "search_config", '{"query":"gcode", "include_unincluded":true, "max_matches":1}'
        ),
        tool_context,
    )
    assert not result["matches"][0]["in_active_tree"] and result["truncated"]
    assert result["matches"][0]["source"]["path"] == "inactive.cfg"
    assert (
        await registry.execute(
            ToolCall("1", "search_config", '{"query":"no matches"}'), tool_context
        )
    )["matches"] == []
    tool_context.diagnostic_artifacts["d"] = ArtifactInput(content="x" * 11000)
    result = await registry.execute(
        ToolCall("1", "read_diagnostic_artifact", '{"artifact_id":"d"}'), tool_context
    )
    assert result["truncated"] and len(result["source"]["excerpt"]) == 10000
    assert "error" in await registry.execute(
        ToolCall("1", "read_diagnostic_artifact", '{"artifact_id":"d", "start_line":2}'),
        tool_context,
    )
    tool_context.moonraker.list_printer_objects.return_value = [
        f"temperature_sensor sensor{i}" for i in range(30)
    ]
    result = await registry.execute(
        ToolCall("1", "get_printer_objects", '{"group":"sensors"}'), tool_context
    )
    assert result["truncated"] and len(result["objects"]) == 24


@pytest.mark.asyncio
async def test_diagnostics_snapshot_reuse_reports_selection_and_omissions(tool_context):
    tool_context.services.collector.collect.return_value.artifacts = [
        ArtifactInput(
            label=f"log-{i}", content="Selection: last 100 line(s)\n" + "evidence\n" * 150
        )
        for i in range(14)
    ]
    tool = DiagnosticsTool()
    result = await tool.execute(DiagnosticsArguments(), tool_context)
    assert result["omitted_artifacts"] == 2 and result["truncated"]
    assert "Selection: last 100" in result["context_notes"]
    assert "middle omitted" in result["artifacts"][0]["content"]
    await tool.execute(DiagnosticsArguments(), tool_context)
    tool_context.services.collector.collect.assert_awaited_once()


@pytest.mark.asyncio
async def test_large_file_tools_expand_only_collected_references_and_reject_changed_content(
    tool_context, tmp_path
):
    path = tmp_path / "config/printer.cfg"
    content = (
        "[printer]\nkinematics: corexy\n"
        + "# filler evidence\n" * 3000
        + "[gcode_macro FINAL]\ngcode: G28\n"
    )
    path.write_text(content, encoding="utf-8")
    tool_context.services.config_collector = ConfigCollector(tmp_path, max_chars_per_document=24000)
    line = len(content.splitlines())
    model = ScriptedModel(
        call("inspect_config", {"section": "gcode_macro FINAL"}),
        call("read_config_file", {"path": "printer.cfg", "start_line": line}, "2"),
        call("search_config", {"query": "FINAL"}, "3"),
        answer(),
    )
    result = await AgentWorkflow(model, tool_context.moonraker, AgentLimits()).ainvoke(
        {"user_message": "Find FINAL"}, context=tool_context.services
    )
    assert result["agent_status"] == "completed"
    assert any(
        source["line_number"] == line and "G28" in source["excerpt"]
        for source in result["source_citations"]
    )
    assert any(
        source["section"] == "gcode_macro FINAL" and "G28" in source["excerpt"]
        for source in result["source_citations"]
    )
    assert "FINAL" in model.conversations[-1][-1]["output"]
    assert path.read_text(encoding="utf-8") == content
    registry = ToolRegistry([InspectConfigTool(), ReadConfigTool()], AgentLimits())
    await tool_context.config()
    path.write_text(content + "# edited\n", encoding="utf-8")
    error = await registry.execute(
        ToolCall("1", "read_config_file", '{"path":"printer.cfg"}'), tool_context
    )
    assert "changed during" in error["error"]
    assert not tool_context.expanded_documents
    path.write_text(content + "x" * 1_000_001, encoding="utf-8")
    error = await registry.execute(
        ToolCall("2", "read_config_file", '{"path":"printer.cfg"}'), tool_context
    )
    assert "full-read limit" in error["error"]


@pytest.mark.asyncio
async def test_failed_diagnostic_collection_can_recover_within_the_request(tool_context):
    ready = tool_context.services.collector.collect.return_value
    tool_context.services.collector.collect.side_effect = [
        DiagnosticsSnapshot(False, None, []),
        ready,
    ]
    registry = ToolRegistry([DiagnosticsTool()], AgentLimits())
    assert "error" in await registry.execute(
        ToolCall("1", "collect_diagnostics", "{}"), tool_context
    )
    assert "artifacts" in await registry.execute(
        ToolCall("2", "collect_diagnostics", "{}"), tool_context
    )
    assert tool_context.services.collector.collect.await_count == 2


def test_mode_schema_and_json_budget():
    assert ChatRequest(session_id="s", message="hello").mode == "chat"
    with pytest.raises(ValidationError):
        InvestigationRequest(user_message="hi", mode="unsafe")
    for size in (150, 900, 4000):
        result = fit_result({"text": '\\"\u2603' * 5000}, size)
        assert len(json.dumps(result)) <= size and result["truncated"]


@pytest.mark.asyncio
async def test_modes_survive_saved_turns_and_switch_without_losing_history(persistent_service):
    service, model = persistent_service
    session = await service.create_ui_session()
    bootstrap = await service.bootstrap(session.session_id)
    assert bootstrap.agent_modes == ["chat", "debug"]
    first = await service.chat(
        ChatRequest(session_id=session.session_id, message="fan", mode="debug")
    )
    assert first.mode == "debug" and first.context_included
    stored = await service.investigations.get(first.thread_id)
    assert stored.turns[-1].result.context_included == first.context_included
    second = await service.chat(
        ChatRequest(
            session_id=session.session_id, thread_id=first.thread_id, message="explain", mode="chat"
        )
    )
    assert second.mode == "chat" and second.thread_id == first.thread_id
    assert "Read fan configuration" in model.requests[-1]["recent_conversation"]
    service.agent_workflow = None
    assert not (await service.bootstrap(session.session_id)).agent_modes
    with pytest.raises(ValueError, match="Debug mode requires"):
        await service.chat(ChatRequest(session_id=session.session_id, message="hi", mode="debug"))
