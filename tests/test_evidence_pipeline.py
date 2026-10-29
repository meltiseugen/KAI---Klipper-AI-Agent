from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import Field
from test_agent import ScriptedModel, answer
from test_agent import tool_context as tool_context
from test_investigations import persistent_service as persistent_service

import klipperai_agent.web.app as app_module
from klipperai_agent.agent.models import AgentLimits, ToolCall
from klipperai_agent.agent.registry import ToolRegistry
from klipperai_agent.agent.tools.base import Tool, ToolArguments
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.contracts.api import ChatRequest
from klipperai_agent.diagnostics.collector import DiagnosticsCollector
from klipperai_agent.diagnostics.rules import RuleEngine
from klipperai_agent.domain.evidence import ArtifactInput
from klipperai_agent.providers.models import DiagnosisLLMOutput
from klipperai_agent.runtime.settings import Settings
from klipperai_agent.workflows.engine import build_diagnosis_graph


class Choice(ToolArguments):
    value: int = Field(default=1, ge=1, le=2)


class ChoiceTool(Tool[Choice]):
    name = "choice"
    label = "Read evidence"
    description = "Fixture only"
    arguments_type = Choice

    async def execute(self, arguments, context):
        return {"value": arguments.value}


@pytest.mark.asyncio
async def test_normalized_cached_observations_match_the_actual_tool_result(tool_context):
    registry = ToolRegistry([ChoiceTool()], AgentLimits())
    await registry.execute(ToolCall("1", "choice", '{"value": 1}'), tool_context)
    first = registry.model_result("choice")
    await registry.execute(ToolCall("2", "choice", '{"value": 2}'), tool_context)
    assert registry.model_result("choice")["value"] == 2
    await registry.execute(ToolCall("3", "choice", '{"value": 1}'), tool_context)
    cached = registry.model_result("choice")
    assert cached["value"] == 1 and cached["_artifact"]["id"] == first["_artifact"]["id"]
    assert len(tool_context.evidence) == 2


@pytest.mark.asyncio
async def test_invalid_or_oversized_observations_are_explicit_before_the_model(tool_context):
    tool = ChoiceTool()
    tool.execute = AsyncMock(return_value={"metric": float("inf")})
    registry = ToolRegistry([tool], AgentLimits(max_result_chars=40000))
    assert "error" in await registry.execute(ToolCall("1", "choice", "{}"), tool_context)
    assert registry.model_result("choice")["_artifact"]["status"] == "unavailable"
    tool.execute.return_value = {"value": "x" * 30000}
    await registry.execute(ToolCall("2", "choice", "{}"), tool_context)
    result = registry.model_result("choice")
    assert result["truncated"] and result["_artifact"]["status"] == "partial"
    assert result["_artifact"]["content_format"] == "text"
    assert len(result["excerpt"]) <= 16000
    assert tool_context.context_included[-1].status == "partial"
    await registry.execute(ToolCall("3", "choice", "{}"), tool_context)
    assert registry.model_result("choice")["_artifact"]["id"] == result["_artifact"]["id"]
    assert tool.execute.await_count == 2


def wire_diagnostics(service):
    printer = SimpleNamespace(
        get_server_info=AsyncMock(return_value={"klippy_connected": True}),
        get_printer_info=AsyncMock(return_value={"state": "shutdown"}),
        list_printer_objects=AsyncMock(return_value=["webhooks", "configfile"]),
        query_printer_objects=AsyncMock(
            return_value={
                "webhooks": {"state": "shutdown"},
                "configfile": {"save_config_pending": False},
            }
        ),
    )
    system = SimpleNamespace(
        collect=lambda: (
            [
                ArtifactInput(
                    kind="system_log", label="klipper.service", content="ActiveState=failed"
                )
            ],
            [],
        )
    )
    service.workflow_context.collector = DiagnosticsCollector(printer, host_system=system)
    service.workflow_context.rules = RuleEngine()
    return printer


def fault_attachment():
    return {
        "kind": "klippy_log",
        "label": "uploaded.log",
        "content": "normal entry\n" * 2500
        + "api_key=private-fixture-credential\nHeater extruder not heating at expected rate\nMove out of range: 400 0 0\n",
        "origin": "host",
        "freshness": "current_snapshot",
    }


def test_json_stream_and_saved_history_return_ranked_source_linked_evidence(
    monkeypatch, tmp_path, persistent_service
):
    service, _ = persistent_service
    printer = wire_diagnostics(service)
    first = answer("Failure signatures are observed; the physical cause is unconfirmed.")
    first.output.append({"type": "reasoning", "encrypted_content": "opaque-provider-state"})
    model = ScriptedModel(first, answer())
    service.agent_workflow = AgentWorkflow(model, printer, AgentLimits())
    monkeypatch.setattr(app_module, "get_settings", lambda: Settings(data_dir=tmp_path / "data"))
    monkeypatch.setattr(
        app_module,
        "build_container",
        lambda _: SimpleNamespace(
            chat_service=service, sessions=service.sessions, aclose=AsyncMock()
        ),
    )
    with TestClient(app_module.create_app()) as client:
        session = client.post("/api/ui-sessions").json()["session_id"]
        for endpoint in ("/api/chat", "/api/chat/stream"):
            response = client.post(
                endpoint,
                json={
                    "session_id": session,
                    "mode": "debug",
                    "message": "Investigate heater failure",
                    "artifacts": [fault_attachment()],
                },
            )
            assert response.status_code == 200
            data = (
                response.json()
                if endpoint == "/api/chat"
                else json.loads(
                    response.text.split("event: result\ndata: ", 1)[1].split("\n\n", 1)[0]
                )
            )
            assert [finding["severity_rank"] for finding in data["findings"]] == [4, 3, 2]
            assert all(
                item["confidence"] == "high" and item["confidence_scope"] == "observation"
                for item in data["findings"]
            )
            blocks = {item["id"]: item for item in data["evidence_blocks"]}
            for finding in data["findings"]:
                assert finding["evidence_ids"][0] in blocks
                assert finding["evidence"] in blocks[finding["evidence_ids"][0]]["content"]
            heater = next(
                item for item in data["findings"] if item["code"] == "heater_heating_failure"
            )
            quote = blocks[heater["evidence_ids"][0]]
            assert quote["origin"] == "user" and quote["freshness"] == "user_supplied"
            assert quote["start_line"] == 2502 and quote["line_basis"] == "excerpt"
            assert quote["citations"][0]["line_number"] == 2502
            assert len(data["evidence_blocks"]) <= 24
            saved = client.get(
                f"/api/investigations/{data['thread_id']}", params={"session_id": session}
            ).json()
            stored_ids = {item["id"] for item in saved["turns"][0]["result"]["evidence"]}
            assert set(blocks) <= stored_ids
            assert "private-fixture-credential" not in response.text + json.dumps(saved)
            assert "opaque-provider-state" not in response.text + json.dumps(saved)
    payload = json.loads(model.conversations[0][1]["content"])
    assert payload["artifacts"][0]["origin"] == "user"
    assert payload["live_status"]["_artifact"]["kind"] == "printer_status"
    assert payload["saved_profile"]["_artifact"]["freshness"] == "saved_configuration"


@pytest.mark.asyncio
async def test_compatibility_provider_gets_typed_context_and_same_public_references(
    persistent_service,
):
    service, _ = persistent_service
    wire_diagnostics(service)
    provider = SimpleNamespace(
        analyze=AsyncMock(return_value=DiagnosisLLMOutput(summary="Review the evidence"))
    )
    service.agent_workflow = None
    service.diagnosis_graph = build_diagnosis_graph()
    service.workflow_context.llm = provider
    service.workflow_context.intent_router = None
    session = await service.create_ui_session()
    result = await service.chat(
        ChatRequest(
            session_id=session.session_id,
            message="Diagnose heater failure",
            artifacts=[fault_attachment()],
        )
    )
    payload = provider.analyze.call_args.args[0]
    assert payload.context_artifacts and all(item.observed_at for item in payload.context_artifacts)
    assert any(item.origin == "user" for item in payload.context_artifacts)
    assert any(item.kind == "config_file" for item in payload.context_artifacts)
    ids = {item.id for item in result.evidence_blocks}
    assert all(finding.evidence_ids[0] in ids for finding in result.findings)
