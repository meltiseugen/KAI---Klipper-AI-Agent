from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from test_agent import ScriptedModel, answer, call
from test_agent import tool_context as tool_context
from test_investigations import persistent_service as persistent_service
from test_shutdown import START, stats

import klipperai_agent.web.app as app_module
from klipperai_agent.agent.models import AgentLimits, ToolCall
from klipperai_agent.agent.registry import ToolRegistry
from klipperai_agent.agent.tools.shutdown import ShutdownTool
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.domain.shutdown import HostObservation, LogExcerpt, ShutdownLogs
from klipperai_agent.infrastructure.host.shutdown import ShutdownCollector
from klipperai_agent.infrastructure.host.system import CommandResult
from klipperai_agent.runtime.settings import Settings


def reader(content=None, host=None):
    return SimpleNamespace(
        read_logs=AsyncMock(
            return_value=ShutdownLogs(
                [
                    LogExcerpt(
                        "klippy.log.1",
                        content
                        or "\n".join(
                            [
                                START,
                                stats(101),
                                stats(102, invalid=8),
                                "MCU 'toolhead' shutdown: Timer too close",
                            ]
                        ),
                    )
                ]
            )
        ),
        read_host=AsyncMock(return_value=host or HostObservation()),
    )


@pytest.mark.asyncio
async def test_chat_tool_report_reaches_next_model_turn_with_citations(tool_context, tmp_path):
    (tmp_path / "config/printer.cfg").write_text(
        "[mcu]\nserial: /dev/serial/by-id/test\n[mcu toolhead]\ncanbus_uuid: test\n[printer]\nkinematics: corexy\n"
    )
    source = reader(
        host=HostObservation(
            kernel=[{"unix_time": 1792058401, "message": "usb 1-1: USB disconnect"}]
        )
    )
    model = ScriptedModel(
        call("investigate_shutdown"),
        answer("Investigate CAN packet ordering; the USB disconnect needs device matching."),
    )
    result = await AgentWorkflow(
        model, tool_context.moonraker, AgentLimits(), shutdown_reader=source
    ).ainvoke({"user_message": "Why the communication error?"}, context=tool_context.services)
    first = json.loads(model.conversations[0][1]["content"])
    assert "shutdown_investigation" not in first
    output = next(
        item for item in model.conversations[-1] if item.get("type") == "function_call_output"
    )
    report = json.loads(output["output"])
    assert report["incident"]["statistics"]["counter_increases"]["toolhead.bytes_invalid"] == 4
    assert report["configured_transports"]["toolhead"] == "CAN"
    assert "serial" in report["configured_transports"]["mcu"]
    assert "packet ordering" in output["output"]
    assert any(citation["path"] == "shutdown:kernel" for citation in result["source_citations"])
    assert any(item["source"] == "investigate_shutdown" for item in result["evidence"])
    assert next(
        item for item in result["context_included"] if item["source"] == "investigate_shutdown"
    )["sent_to_model"]


@pytest.mark.asyncio
async def test_debug_automatically_investigates_and_reuses_result(tool_context):
    source = reader()
    model = ScriptedModel(call("investigate_shutdown"), answer())
    result = await AgentWorkflow(
        model, tool_context.moonraker, AgentLimits(), shutdown_reader=source
    ).ainvoke({"user_message": "Timing error", "mode": "debug"}, context=tool_context.services)
    initial = json.loads(model.conversations[0][1]["content"])
    assert initial["shutdown_investigation"]["incident"]["family"] == "timing"
    source.read_logs.assert_awaited_once()
    assert result["agent_status"] == "completed"


@pytest.mark.asyncio
async def test_tool_rejects_arguments_and_handles_missing_incidents(tool_context):
    source = reader("healthy log")
    tool_context.artifacts = []
    registry = ToolRegistry([ShutdownTool(source)], AgentLimits())
    for args in (
        {"incident_index": True},
        {"incident_index": "0"},
        {"incident_index": 1.2},
        {"incident_index": -1},
        {"incident_index": 10},
        {"path": "/etc/passwd"},
        {"command": "restart"},
    ):
        result = await registry.execute(
            ToolCall("1", "investigate_shutdown", json.dumps(args)), tool_context
        )
        assert "Invalid tool arguments" in result["error"]
    source.read_logs.assert_not_awaited()
    assert (
        "No supported shutdown"
        in (await registry.execute(ToolCall("1", "investigate_shutdown", "{}"), tool_context))[
            "error"
        ]
    )
    source.read_logs.return_value = reader().read_logs.return_value
    assert (
        "Incident index unavailable"
        in (
            await registry.execute(
                ToolCall("2", "investigate_shutdown", '{"incident_index": 2}'), tool_context
            )
        )["error"]
    )
    result = await registry.execute(ToolCall("3", "investigate_shutdown", "{}"), tool_context)
    assert result["incident"] and source.read_logs.await_count == 3


@pytest.mark.asyncio
async def test_tool_reports_partial_sources_missing_config_and_incident_selection(tool_context):
    source = reader(
        "\n".join(
            [
                START,
                stats(102),
                "Timer too close",
                "Start printer at unknown",
                "Communication interrupted",
            ]
            * 6
        )
    )
    source.read_logs.return_value.excerpts[0].partial = True
    tool_context.services.config_collector = SimpleNamespace(
        collect_with_options=Mock(side_effect=OSError())
    )
    registry = ToolRegistry([ShutdownTool(source)], AgentLimits())
    result = await registry.execute(
        ToolCall("1", "investigate_shutdown", '{"incident_index": 1}'), tool_context
    )
    assert result["truncated"] and len(result["available_incidents"]) == 10
    assert result["incident"]["family"] == "timing"
    assert "transports unconfirmed" in str(result["context_notes"])
    assert tool_context.context_included[-1].status == "partial"


@pytest.mark.asyncio
async def test_tool_timeout_and_cancellation_use_existing_run_deadline(tool_context):
    source = reader()

    async def slow():
        await asyncio.sleep(1)

    source.read_logs.side_effect = slow
    registry = ToolRegistry([ShutdownTool(source)], AgentLimits(tool_timeout_seconds=0.01))
    assert (
        "timed out"
        in (await registry.execute(ToolCall("1", "investigate_shutdown", "{}"), tool_context))[
            "error"
        ]
    )
    source.read_host.assert_not_awaited()


@pytest.mark.asyncio
async def test_large_incident_report_retains_structured_evidence_and_marks_omissions(tool_context):
    names = [f"tool{i}_" + "long_mcu_name_" * 6 for i in range(20)]
    before = " ".join(f"{name}: bytes_invalid=0 bytes_retransmit=0" for name in names)
    after = " ".join(f"{name}: bytes_invalid=30 bytes_retransmit=40" for name in names)
    warnings = ["Got error -1 in can write: (105)No buffer space available " + "details " * 50] * 8
    content = "\n".join(
        [START, f"Stats 101: {before}", *warnings, f"Stats 102: {after}", "Timer too close"] * 10
    )
    events = [
        {
            "unix_time": 1792058401,
            "message": "usb 1-1: USB disconnect, " + "long device descriptor " * 70,
        }
    ] * 4
    source = reader(content, HostObservation(kernel=events))
    registry = ToolRegistry([ShutdownTool(source)], AgentLimits())
    result = await registry.execute(ToolCall("1", "investigate_shutdown", "{}"), tool_context)
    assert result["truncated"] and result["omitted_assessments"] > 0
    assert len(result["assessments"]) < 8
    assert result["incident"]["family"] == "timing" and "excerpt" not in result
    assert len(json.dumps(result, ensure_ascii=False)) < 16000


def test_real_readers_debug_http_and_persisted_evidence(monkeypatch, tmp_path, persistent_service):
    service, _ = persistent_service
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "klippy.log").write_text("healthy current run")
    (logs / "klippy.log.1").write_text(
        "\n".join(
            [START, stats(101), stats(102, memory=10000), "Lost communication with MCU 'mcu'"]
        )
    )
    host = SimpleNamespace(
        get_process_stats=AsyncMock(return_value={"system_memory": {"available": 300000}})
    )
    runner = SimpleNamespace(
        run=Mock(
            return_value=CommandResult(
                (),
                0,
                json.dumps(
                    {
                        "__REALTIME_TIMESTAMP": "1792058401500000",
                        "MESSAGE": "Out of memory: Killed process 123 (klippy)",
                    }
                ),
                "",
            )
        )
    )
    source = ShutdownCollector(host, logs, logs_enabled=True, journal_enabled=True, runner=runner)
    model = ScriptedModel(
        answer("An OOM event occurred near the stop; inspect the killed process and memory growth.")
    )
    moonraker = SimpleNamespace(
        get_printer_info=AsyncMock(return_value={"state": "ready"}),
        list_printer_objects=AsyncMock(return_value=[]),
        query_printer_objects=AsyncMock(return_value={}),
    )
    service.agent_workflow = AgentWorkflow(model, moonraker, AgentLimits(), shutdown_reader=source)
    settings = Settings(printer_data_root=tmp_path, data_dir=tmp_path / "data")
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        app_module,
        "build_container",
        lambda _: SimpleNamespace(
            chat_service=service, sessions=service.sessions, aclose=AsyncMock()
        ),
    )
    with TestClient(app_module.create_app()) as client:
        session = client.post("/api/ui-sessions").json()["session_id"]
        result = client.post(
            "/api/chat",
            json={
                "session_id": session,
                "mode": "debug",
                "message": "Printer stopped with a communication error",
            },
        )
        assert result.status_code == 200
        data = result.json()
        assert "OOM" in data["response"]
        assert any(item["path"] == "shutdown:klippy.log.1" for item in data["source_citations"])
        saved = client.get(
            f"/api/investigations/{data['thread_id']}", params={"session_id": session}
        )
        assert saved.status_code == 200 and "investigate_shutdown" in saved.text
        assert "Host memory exhaustion" in saved.text and "current_host" in saved.text
    assert "Host memory exhaustion" in json.dumps(model.conversations[0])
