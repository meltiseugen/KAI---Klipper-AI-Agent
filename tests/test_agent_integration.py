from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import klipperai_agent.bootstrap.container as container_module
import klipperai_agent.web.app as app_module
from klipperai_agent.agent.models import AgentLimits, ModelTurn, ToolCall
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.application.chat import ChatService
from klipperai_agent.application.sessions import InMemorySessionStore
from klipperai_agent.contracts.api import AgentEvent, ChatRequest
from klipperai_agent.profile.models import PrinterProfile
from klipperai_agent.runtime.settings import Settings
from klipperai_agent.web.streaming import ChatEventStream


class ProfileModel:
    async def respond(self, conversation, tools):
        if any(item.get("type") == "function_call_output" for item in conversation):
            return ModelTurn([], text=json.dumps({"response": "Your saved firmware is Kalico."}))
        output = {
            "type": "function_call",
            "call_id": "profile",
            "name": "get_printer_profile",
            "arguments": "{}",
        }
        return ModelTurn([output], [ToolCall("profile", "get_printer_profile", "{}")])


@pytest.fixture
def agent_service():
    context = SimpleNamespace(
        profile=PrinterProfile(firmware_flavor="Kalico"),
        collector=SimpleNamespace(
            ping=AsyncMock(return_value=True), ping_printer=AsyncMock(return_value=True)
        ),
        intent_router=SimpleNamespace(
            classify=AsyncMock(side_effect=AssertionError("Agent should select its own tools"))
        ),
    )
    return ChatService(
        provider_name="openai",
        root_path="",
        diagnosis_graph=None,
        config_graph=None,
        workflow_context=context,
        sessions=InMemorySessionStore(60),
        agent_workflow=AgentWorkflow(ProfileModel(), SimpleNamespace(), AgentLimits()),
    )


@pytest.mark.asyncio
async def test_chat_exposes_actions_and_capabilities_without_router_preflight(agent_service):
    session = await agent_service.create_ui_session()
    bootstrap = await agent_service.bootstrap(session.session_id)
    assert "tool-using-agent" in bootstrap.features and "web-search" not in bootstrap.features
    response = await agent_service.chat(
        ChatRequest(session_id=session.session_id, message="Which firmware?")
    )
    assert response.response == "Your saved firmware is Kalico."
    assert response.agent_events[0].tool == "get_printer_profile"
    assert response.agent_status == "completed"
    agent_service.workflow_context.intent_router.classify.assert_not_called()


def test_stream_endpoint_session_validation_events_final_and_assets(
    monkeypatch, tmp_path, agent_service
):
    settings = Settings(
        data_dir=tmp_path / "data", printer_data_root=tmp_path, checkpoint_db=tmp_path / "db"
    )
    container = SimpleNamespace(
        sessions=agent_service.sessions,
        chat_service=agent_service,
        aclose=AsyncMock(),
    )
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(app_module, "build_container", lambda _: container)
    with TestClient(app_module.create_app()) as client:
        session = client.post("/api/ui-sessions").json()["session_id"]
        response = client.post(
            "/api/chat/stream", json={"session_id": session, "message": "Which firmware?"}
        )
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        assert (
            response.text.index('"tool_started"')
            < response.text.index('"tool_completed"')
            < response.text.index("event: result")
        )
        assert '"agent_status": "completed"' in response.text
        assert (
            client.post("/api/chat/stream", json={"session_id": "bad", "message": "hi"}).status_code
            == 403
        )
        assert "class ChatStreamReader" in client.get("/").text
        assert client.get("/assets/agent.js").status_code == 200
        assert client.post(
            "/api/chat", json={"session_id": session, "message": "Which firmware?"}
        ).json()["agent_events"]
    container.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_errors_and_disconnect_cancel_producer():
    payload = ChatRequest(session_id="s", message="test")
    service = SimpleNamespace(chat=AsyncMock(side_effect=RuntimeError("private error details")))
    events = [event async for event in ChatEventStream(service).events(payload)]
    assert "event: error" in events[0] and "private error details" not in events[0]
    cancelled = asyncio.Event()

    async def slow_chat(payload, on_event):
        try:
            await on_event(AgentEvent(kind="tool_started", message="Checking"))
            await asyncio.sleep(10)
        finally:
            cancelled.set()

    stream = ChatEventStream(SimpleNamespace(chat=slow_chat), heartbeat_seconds=0.001).events(
        payload
    )
    assert "event: agent" in await anext(stream)
    assert "keep-alive" in await anext(stream)
    assert "keep-alive" in await anext(stream)
    await stream.aclose()
    assert cancelled.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("search,key", [(True, "key"), (False, None)])
async def test_container_wires_agent_and_closes_provider_client(monkeypatch, tmp_path, search, key):
    responses = SimpleNamespace(aclose=AsyncMock())
    moonraker = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(container_module, "ResponsesClient", lambda *args, **kwargs: responses)
    monkeypatch.setattr(container_module, "MoonrakerClient", lambda *args: moonraker)
    settings = Settings(
        printer_data_root=tmp_path,
        llm_provider="openai",
        openai_api_key=key,
        web_search_enabled=search,
        collect_systemd_diagnostics=False,
    )
    container = container_module.build_container(settings)
    assert container.chat_service.agent_workflow.web_search_enabled is search
    await container.aclose()
    responses.aclose.assert_awaited_once()
    moonraker.aclose.assert_awaited_once()
