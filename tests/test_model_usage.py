import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from klipperai_agent.agent.models import AgentLimits
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.contracts.api import ChatRequest
from klipperai_agent.domain.investigation import InvestigationResult, PendingInvestigation
from klipperai_agent.providers.json_client import OpenAIJsonClient
from klipperai_agent.providers.responses import OpenAIAgentModel, ProviderError, ResponsesClient
from klipperai_agent.runtime.model_usage import model_request, track_model_usage
from klipperai_agent.web.streaming import ChatEventStream
from tests.test_investigations import persistent_service as persistent_service


@pytest.mark.asyncio
async def test_receipt_counts_http_attempts_and_successes_without_exposing_content():
    events = AsyncMock()
    responses = [
        httpx.Response(200, json={"status": "completed", "output": []}),
        httpx.Response(401),
    ]
    client = ResponsesClient(
        "selected-model", "private-key", transport=httpx.MockTransport(lambda _: responses.pop(0))
    )
    try:
        with track_model_usage(events) as receipt:
            await client.create(input="private context")
            with pytest.raises(ProviderError):
                await client.create(input="private context")
        assert receipt.requests_started == 2 and receipt.requests_completed == 1
        assert receipt.models == ["OpenAI / selected-model"]
        assert receipt.status == "attempted"
        assert [call.args[0].kind for call in events.await_args_list] == [
            "model_started",
            "model_completed",
            "model_started",
        ]
        assert "private" not in receipt.json()
        # Missing credentials fail before a provider attempt is recorded.
        client._api_key = None
        with track_model_usage() as empty:
            with pytest.raises(ProviderError):
                await client.create(input="test")
        assert empty.status == "not_used" and empty.requests_started == 0
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_usage_scopes_are_isolated_between_concurrent_runs_and_reset_after_errors():
    async def run(name):
        with track_model_usage() as receipt:
            async with model_request(name):
                await asyncio.sleep(0)
        return receipt

    first, second = await asyncio.gather(run("first"), run("second"))
    assert first.models == ["OpenAI / first"] and second.models == ["OpenAI / second"]
    assert first.requests_completed == second.requests_completed == 1
    with pytest.raises(RuntimeError), track_model_usage() as failed:
        async with model_request("failed"):
            raise RuntimeError("test")
    assert failed.requests_completed == 0
    async with model_request("outside"):
        pass
    assert failed.requests_started == 1


@pytest.mark.asyncio
async def test_legacy_client_counts_requests_with_and_without_a_completed_response(monkeypatch):
    real_client = httpx.AsyncClient
    responses = [
        httpx.Response(200, json={"choices": [{"message": {"content": '{"summary":"ok"}'}}]}),
        httpx.Response(503),
    ]
    monkeypatch.setattr(
        "klipperai_agent.providers.json_client.httpx.AsyncClient",
        lambda **kwargs: real_client(
            **kwargs, transport=httpx.MockTransport(lambda _: responses.pop(0))
        ),
    )
    client = OpenAIJsonClient("legacy-model", "private-key")
    with track_model_usage() as receipt:
        assert await client.complete_json(system_prompt="JSON", user_prompt="test") == {
            "summary": "ok"
        }
        with pytest.raises(httpx.HTTPStatusError):
            await client.complete_json(system_prompt="JSON", user_prompt="test")
    assert receipt.requests_started == 2 and receipt.requests_completed == 1
    assert receipt.models == ["OpenAI / legacy-model"]


@pytest.mark.asyncio
async def test_agent_receipts_and_failed_attempts_survive_saved_investigations(persistent_service):
    service, _ = persistent_service
    responses = [
        httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps({"response": "Agent answer"}),
                            }
                        ],
                    }
                ],
            },
        ),
        httpx.Response(401),
    ]
    client = ResponsesClient(
        "agent-model", "key", transport=httpx.MockTransport(lambda _: responses.pop(0))
    )
    service.agent_workflow = AgentWorkflow(
        OpenAIAgentModel(client), SimpleNamespace(), AgentLimits()
    )
    session = await service.create_ui_session()
    events = AsyncMock()
    try:
        result = await service.chat(
            ChatRequest(session_id=session.session_id, message="Tell me about my printer"),
            on_event=events,
        )
        assert result.response == "Agent answer"
        assert result.model_usage.status == "completed"
        saved = await service.investigations.get(result.thread_id)
        assert saved.turns[-1].result.model_usage == result.model_usage
        failed = await service.chat(
            ChatRequest(
                session_id=session.session_id, message="Continue", thread_id=result.thread_id
            )
        )
        assert failed.agent_status == "error"
        assert failed.model_usage.status == "attempted"
        assert failed.model_usage.requests_completed == 0
        assert any(call.args[0].kind == "model_started" for call in events.await_args_list)
    finally:
        await client.aclose()
    assert InvestigationResult(response_text="Old answer").model_usage.status == "unknown"


@pytest.mark.asyncio
async def test_stream_failure_includes_usage_but_not_private_error(persistent_service):
    service, _ = persistent_service
    service.agent_workflow = None
    client = ResponsesClient(
        "agent-model", "private-key", transport=httpx.MockTransport(lambda _: httpx.Response(401))
    )

    async def fail(*_args, **_kwargs):
        await client.create(input="private context")

    service.diagnosis_graph = SimpleNamespace(ainvoke=fail)
    try:
        events = [
            event
            async for event in ChatEventStream(service).events(
                ChatRequest(
                    session_id=(await service.create_ui_session()).session_id,
                    message="Why did it fail?",
                )
            )
        ]
    finally:
        await client.aclose()
    error = json.loads(events[-1].split("data: ")[1])
    assert error["model_usage"]["requests_started"] == 1
    assert error["model_usage"]["requests_completed"] == 0
    assert "private" not in events[-1]


@pytest.mark.asyncio
async def test_recovery_without_key_stops_before_running_an_investigation(persistent_service):
    service, model = persistent_service
    service.provider_ready = False
    investigation = await service.investigations.open(None, "Audit active config")
    await service.investigations.begin(
        investigation, PendingInvestigation(message="Audit active config"), "owner"
    )
    await service.resume(investigation, "owner")
    saved = await service.investigations.get(investigation.id)
    assert saved.turns[-1].result.agent_status == "limited"
    assert saved.turns[-1].result.model_usage.status == "not_used"
    assert not model.requests
