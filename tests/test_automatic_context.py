"""Questions alone collect printer files before the first model call."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from klipperai_agent.agent.models import AgentLimits
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.application.chat import ChatService
from klipperai_agent.application.sessions import InMemorySessionStore
from klipperai_agent.config.collector import ConfigCollector
from klipperai_agent.contracts.api import ChatRequest
from klipperai_agent.diagnostics.collector import DiagnosticsCollector
from klipperai_agent.diagnostics.rules import RuleEngine
from klipperai_agent.infrastructure.host.logs import HostLogCollector
from klipperai_agent.infrastructure.moonraker import MoonrakerError
from klipperai_agent.profile.models import PrinterProfile
from tests.test_agent import ScriptedModel, answer


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["chat", "debug"])
async def test_question_alone_loads_real_config_and_logs_even_if_moonraker_is_unavailable(
    tmp_path, mode
):
    config = tmp_path / "config"
    config.mkdir()
    (config / "printer.cfg").write_text("[include motors.cfg]\n[printer]\nkinematics: corexy\n")
    (config / "motors.cfg").write_text("[stepper_x]\nstep_pin: PA1\n")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "klippy.log").write_text("MCU 'mcu' shutdown: Timer too close\n")
    (logs / "moonraker.log").write_text("Moonraker started\n")
    printer = SimpleNamespace(
        get_server_info=AsyncMock(side_effect=MoonrakerError("Moonraker unavailable")),
        get_printer_info=AsyncMock(side_effect=MoonrakerError("Klipper unavailable")),
    )
    context = SimpleNamespace(
        config_collector=ConfigCollector(tmp_path),
        collector=DiagnosticsCollector(printer, host_logs=HostLogCollector(tmp_path)),
        rules=RuleEngine(),
        profile=PrinterProfile(),
    )
    model = ScriptedModel(answer("I reviewed the collected printer evidence."))
    service = ChatService(
        provider_name="openai",
        root_path="",
        diagnosis_graph=None,
        config_graph=None,
        workflow_context=context,
        sessions=InMemorySessionStore(60),
        agent_workflow=AgentWorkflow(model, printer, AgentLimits()),
    )
    response = await service.chat(
        ChatRequest(
            session_id=(await service.create_ui_session()).session_id,
            mode=mode,
            message="Why did my printer stop?",
        )
    )
    payload = json.loads(model.conversations[0][1]["content"])
    assert payload["artifacts"] == []
    assert {file["path"] for file in payload["active_config"]["files"]} == {
        "printer.cfg",
        "motors.cfg",
    }
    assert "step_pin: PA1" in json.dumps(payload["active_config"])
    diagnostics = payload["diagnostics"]
    assert {item["label"] for item in diagnostics["artifacts"]} == {"klippy.log", "moonraker.log"}
    assert "Timer too close" in json.dumps(diagnostics)
    assert any(item["code"] == "mcu_timer_too_close" for item in diagnostics["findings"])
    assert any(
        item.source == "collect_diagnostics" and item.sent_to_model
        for item in response.context_included
    )
    assert response.moonraker_reachable is False


@pytest.mark.asyncio
async def test_missing_log_directory_is_reported_to_model_without_requesting_user_supplied_files(
    tmp_path,
):
    config = tmp_path / "config"
    config.mkdir()
    (config / "printer.cfg").write_text("[printer]\nkinematics: corexy\n")
    printer = SimpleNamespace(
        get_server_info=AsyncMock(side_effect=MoonrakerError("Moonraker unavailable")),
    )
    context = SimpleNamespace(
        config_collector=ConfigCollector(tmp_path),
        collector=DiagnosticsCollector(printer, host_logs=HostLogCollector(tmp_path)),
        rules=RuleEngine(),
        profile=PrinterProfile(),
    )
    model = ScriptedModel(answer("The configured log directory is unavailable."))
    result = await AgentWorkflow(model, printer, AgentLimits()).ainvoke(
        {"user_message": "Investigate my printer"}, context=context
    )
    payload = json.loads(model.conversations[0][1]["content"])
    assert "Host log directory does not exist" in json.dumps(payload["diagnostics"])
    assert any(
        item["source"] == "collect_diagnostics" and item["status"] == "unavailable"
        for item in result["context_included"]
    )
