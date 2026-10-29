from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_agent import ScriptedModel, answer, call
from test_agent import tool_context as tool_context
from test_shutdown import START, stats
from test_shutdown_agent import reader

import klipperai_agent.bootstrap.container as container_module
import klipperai_agent.web.app as app_module
from klipperai_agent.agent.models import AgentLimits
from klipperai_agent.agent.tools.shutdown import ShutdownArguments, ShutdownTool
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.diagnostics.collector import DiagnosticsCollector
from klipperai_agent.diagnostics.host_history import summarize_history
from klipperai_agent.domain.host_history import HostSample, PressureSample
from klipperai_agent.domain.shutdown import HostObservation
from klipperai_agent.infrastructure.host.system import CommandResult, HostSystemCollector
from klipperai_agent.infrastructure.moonraker import MoonrakerClient, MoonrakerError
from klipperai_agent.infrastructure.moonraker_state import (
    CORE_OBJECTS,
    collect_core_state,
    public_fields,
)
from klipperai_agent.runtime.settings import Settings, _load_klipperai_cfg_values


def test_opt_in_settings_config_and_environment_validation(tmp_path, monkeypatch):
    assert not Settings().host_flight_recorder_enabled
    config = tmp_path / "diagnostics.cfg"
    config.write_text(
        "[system]\nadditional_journal_units: crowsnest.service, nginx.service\n[flight_recorder]\nhost_flight_recorder_enabled: true\nhost_flight_recorder_interval_seconds: 5\nhost_flight_recorder_max_samples: 24\n"
    )
    settings = Settings(**_load_klipperai_cfg_values(config))
    assert settings.additional_journal_units == ["crowsnest.service", "nginx.service"]
    assert settings.host_flight_recorder_enabled and settings.host_flight_recorder_max_samples == 24
    monkeypatch.setenv(
        "KLIPPERAI_ADDITIONAL_JOURNAL_UNITS", "crowsnest.service,nginx.service,crowsnest.service"
    )
    assert Settings().additional_journal_units == settings.additional_journal_units
    monkeypatch.setenv("KLIPPERAI_LOG_TAIL_LINES_OVERRIDES", '{"klippy": 10}')
    assert Settings().log_tail_lines_overrides == {"klippy": 10}
    for value in (
        2,
        ["*"],
        ["../host.service"],
        ["--user"],
        ["a.service; id"],
        [f"unit{i}.service" for i in range(7)],
    ):
        with pytest.raises(ValidationError):
            Settings(additional_journal_units=value)
    assert Settings(additional_journal_units=" ").additional_journal_units == []
    for args in (
        {"host_flight_recorder_interval_seconds": 0},
        {"host_flight_recorder_max_samples": 9000},
    ):
        with pytest.raises(ValidationError):
            Settings(**args)


def test_additional_journals_are_fixed_bounded_opt_in_and_permission_tolerant():
    commands = []

    def run(command, *, max_output_bytes):
        commands.append((command, max_output_bytes))
        if "crowsnest.service" in command:
            return CommandResult(command, 0, "api_key=private\nmessage", "", True)
        return CommandResult(command, 0, "normal", "")

    collector = HostSystemCollector(
        additional_journal_units=("crowsnest.service", "moonraker.service", "crowsnest.service"),
        journal_lines=2000,
        runner=SimpleNamespace(run=run),
    )
    artifacts, notes = collector.collect()
    assert len(artifacts) == 5 and len(commands) == 5
    extra, limit = commands[-1]
    assert extra[:3] == ("journalctl", "--unit", "crowsnest.service")
    assert extra[-1] == "1000" and limit == 262144
    assert "incomplete" in str(notes) and "private" not in artifacts[-1].content
    assert all(
        command[0] != "systemctl" for command, _ in commands if "crowsnest.service" in command
    )
    assert HostSystemCollector()._additional_journals == ()
    with pytest.raises(ValueError):
        HostSystemCollector(additional_journal_units=("--all",))
    unavailable = HostSystemCollector(
        runner=SimpleNamespace(run=Mock(side_effect=PermissionError()))
    )
    assert unavailable.collect()[0] == []
    assert "unavailable" in str(unavailable.collect()[1])


@pytest.mark.asyncio
async def test_core_moonraker_queries_metadata_and_prompt_evidence():
    requests = []
    loaded = {
        "printer": {"kinematics": "corexy"},
        "gcode_macro PRIVATE": {"gcode": "api_key=never-send-config-values"},
    }

    def handler(request):
        requests.append(
            (
                request.method,
                request.url.path,
                json.loads(request.content) if request.content else None,
            )
        )
        data = {
            "/server/info": {
                "klippy_connected": True,
                "klippy_state": "ready",
                "moonraker_version": "v0.9",
                "api_key": "server-secret",
            },
            "/printer/info": {
                "state": "ready",
                "config_file": "/printer/config/printer.cfg",
                "software_version": "v0.13",
                "private": "secret",
            },
            "/printer/objects/list": {"objects": list(CORE_OBJECTS) + ["gcode", "untrusted"]},
            "/printer/objects/query": {
                "status": {
                    "webhooks": {"state": "ready"},
                    "extruder": {"temperature": 25, "target": 0, "secret": "no"},
                    "configfile": {
                        "config": loaded,
                        "save_config_pending": True,
                        "warnings": [{"type": "deprecated_option", "message": "old option"}, 1],
                    },
                }
            },
        }
        return httpx.Response(200, json={"result": data[request.url.path]})

    client = MoonrakerClient("http://printer")
    await client.aclose()
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://printer"
    )
    snapshot = await DiagnosticsCollector(client).collect([])
    evidence = json.loads(snapshot.artifacts[0].content)
    assert snapshot.moonraker_reachable and evidence["server_info"]["klippy_state"] == "ready"
    assert evidence["config_metadata"]["section_names"] == list(loaded)
    assert evidence["config_metadata"]["save_config_pending"]
    assert evidence["config_metadata"]["warning_count"] == 2
    assert "never-send-config-values" not in snapshot.artifacts[0].content
    assert (
        "private" not in snapshot.artifacts[0].content
        and "server-secret" not in snapshot.artifacts[0].content
    )
    assert requests[-1] == ("POST", "/printer/objects/query", {"objects": CORE_OBJECTS})
    assert "Moonraker core state" in snapshot.to_prompt_block()
    await client.aclose()


@pytest.mark.asyncio
async def test_core_state_partial_failures_missing_config_and_bounds():
    client = SimpleNamespace(
        get_printer_info=AsyncMock(side_effect=MoonrakerError("private detail")),
        list_printer_objects=AsyncMock(side_effect=MoonrakerError("private detail")),
    )
    artifact, notes = await collect_core_state(client, {"klippy_connected": False})
    assert len(notes) == 2 and "private detail" not in str(notes)
    assert json.loads(artifact.content)["server_info"] == {"klippy_connected": False}
    client.get_printer_info.return_value = {"state": "shutdown"}
    client.get_printer_info.side_effect = None
    client.list_printer_objects.side_effect = None
    client.list_printer_objects.return_value = []
    assert "metadata unavailable" in str((await collect_core_state(client, {}))[1])
    client.list_printer_objects.return_value = ["configfile"]
    client.query_printer_objects = AsyncMock(
        return_value={"configfile": {"config": {f"s{i}": {} for i in range(100)}, "warnings": []}}
    )
    state = json.loads((await collect_core_state(client, {}))[0].content)
    assert len(state["config_metadata"]["section_names"]) == 80
    assert state["config_metadata"]["section_names_truncated"]
    client.query_printer_objects.return_value = {"configfile": {"config": None, "warnings": None}}
    assert json.loads((await collect_core_state(client, {}))[0].content)["config_metadata"] == {}
    assert public_fields(
        {"a": "x" * 1000, "b": ["x"] * 20, "c": {}, "d": None}, ["a", "b", "c", "d", "missing"]
    ) == {"a": "x" * 500, "b": ["x"] * 8, "d": None}


@pytest.mark.asyncio
async def test_shutdown_history_reaches_model_with_qualified_assessments(tool_context):
    stamp = 1792058402
    history = summarize_history(
        [
            HostSample(
                unix_time=stamp - 1,
                uptime_seconds=100,
                cpu_busy_percent=95,
                pressure={
                    "memory": PressureSample(some_avg10=30),
                    "io": PressureSample(some_avg10=40),
                },
            )
        ],
        stamp,
    )
    source = reader(
        "\n".join([START, stats(102), "Timer too close"]), HostObservation(history=history)
    )
    model = ScriptedModel(
        call("investigate_shutdown"),
        answer("Recorded host pressure preceded the stop; USB/CAN cause remains unconfirmed."),
    )
    result = await AgentWorkflow(
        model, tool_context.moonraker, AgentLimits(), shutdown_reader=source
    ).ainvoke({"user_message": "Investigate latest stop"}, context=tool_context.services)
    output = next(
        item["output"]
        for item in model.conversations[-1]
        if item.get("type") == "function_call_output"
    )
    report = json.loads(output)
    assert report["historical_host"]["sample_count"] == 1
    assert sum("Recorded host" in item["cause"] for item in report["assessments"]) == 3
    assert all("possible contributor" in item["confidence"] for item in report["assessments"])
    assert result["agent_status"] == "completed"


@pytest.mark.asyncio
async def test_history_excerpt_trimming_retains_incident_summary(tool_context):
    source = reader(
        host=HostObservation(
            history={"samples": [{"detail": "x" * 8000}] * 6, "pre_stop_summary": {}}
        )
    )
    report = await ShutdownTool(source).execute(ShutdownArguments(), tool_context)
    assert report["incident"] and report["truncated"]
    assert report["historical_host"]["truncated"]
    assert len(json.dumps(report)) <= 14000


@pytest.mark.asyncio
async def test_recorder_container_opt_in_and_lifespan(monkeypatch, tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        printer_data_root=tmp_path / "printer",
        collect_systemd_diagnostics=False,
        moonraker_agent_enabled=False,
        host_flight_recorder_enabled=True,
    )
    container = container_module.build_container(settings)
    assert container.host_flight_recorder is not None
    start = Mock()
    monkeypatch.setattr(container.host_flight_recorder, "start", start)
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(app_module, "build_container", lambda config: container)
    monkeypatch.setattr(container.moonraker, "ping", AsyncMock(return_value=True))
    with TestClient(app_module.create_app()) as client:
        assert client.get("/healthz").status_code == 200
        start.assert_called_once()
    await container.aclose()
