"""Per-chat model choices survive recovery and never mutate shared provider policy."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from kai_agent.agent.models import AgentLimits
from kai_agent.agent.workflow import AgentWorkflow
from kai_agent.contracts.api import ChatRequest
from kai_agent.domain.investigation import PendingInvestigation
from kai_agent.domain.provider_settings import ModelProfile, ProviderPolicy
from kai_agent.providers.json_client import OpenAIJsonClient
from kai_agent.providers.responses import OpenAIAgentModel, ResponsesClient
from kai_agent.runtime.model_usage import selected_chat_model, track_model_usage
from tests.test_investigations import persistent_service as persistent_service


@pytest.mark.parametrize("model", ["", " a-model", "a/model", "a\nmodel", "a" * 121])
def test_chat_rejects_invalid_model_ids(model):
    with pytest.raises(ValidationError):
        ChatRequest(session_id="session", message="Hello", model=model)
    with pytest.raises(ValidationError):
        PendingInvestigation(message="Hello", model=model)


@pytest.mark.asyncio
async def test_model_override_is_task_local_preserves_policy_and_skips_other_routes():
    requests = []

    async def handler(request):
        await asyncio.sleep(0)
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"status": "completed", "output": []})

    policy = ProviderPolicy(agent=ModelProfile(model="default-model", max_output_tokens=1000))
    client = ResponsesClient(
        "default-model", "key", policy=policy, transport=httpx.MockTransport(handler)
    )

    async def run(model):
        with track_model_usage(chat_model=model) as receipt:
            await client.create(input="question", max_output_tokens=2000)
            assert receipt.models == [f"OpenAI / {model}"]

    try:
        await asyncio.gather(run("chat-a"), run("chat-b"))
        assert {body["model"] for body in requests} == {"chat-a", "chat-b"}
        assert all(
            body["max_output_tokens"] == 1000 and body["store"] is False for body in requests
        )
        with track_model_usage(chat_model="chat-override"):
            await client.create(purpose="search", input="public query")
            await client.create(purpose="knowledge", input="public product")
            with track_model_usage():
                await client.create(input="default question")
            assert selected_chat_model("fallback") == "chat-override"
        assert [body["model"] for body in requests[-3:]] == [
            policy.search.model,
            policy.knowledge.model,
            "default-model",
        ]
        assert policy.agent.model == "default-model"
        assert selected_chat_model("fallback") == "fallback"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_chat_and_recovery_keep_selected_model_in_saved_public_turns(persistent_service):
    service, _ = persistent_service
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": '{"response":"Model choice respected"}'}
                        ],
                    }
                ],
            },
        )

    client = ResponsesClient("printer-default", "key", transport=httpx.MockTransport(handler))
    service.agent_workflow = AgentWorkflow(
        OpenAIAgentModel(client), SimpleNamespace(), AgentLimits()
    )
    session = await service.create_ui_session()
    try:
        result = await service.chat(
            ChatRequest(session_id=session.session_id, message="Hello", model="chat-choice")
        )
        record = await service.investigations.get(result.thread_id)
        assert record.turns[-1].model == "chat-choice"
        assert result.model_usage.models == ["OpenAI / chat-choice"]
        pending = PendingInvestigation(message="Continue", model="recovery-choice")
        await service.investigations.begin(record, pending, "owner")
        restored = await service.investigations.get(record.id)
        assert restored.pending.model == "recovery-choice"
        await service.resume(restored, "owner")
        saved = await service.investigations.get(record.id)
        assert saved.pending is None
        assert saved.turns[-1].model == "recovery-choice"
        assert saved.turns[-1].result.model_usage.models == ["OpenAI / recovery-choice"]
        await service.chat(ChatRequest(session_id=session.session_id, message="New default chat"))
        assert [body["model"] for body in requests] == [
            "chat-choice",
            "recovery-choice",
            "printer-default",
        ]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_legacy_provider_uses_override_with_existing_token_limits(monkeypatch):
    real_client = httpx.AsyncClient
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"summary":"ok"}'}}]})

    monkeypatch.setattr(
        "kai_agent.providers.json_client.httpx.AsyncClient",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)),
    )
    client = OpenAIJsonClient("legacy-default", "key")
    with track_model_usage(chat_model="chat-choice") as receipt:
        await client.complete_json(system_prompt="JSON", user_prompt="Question")
    await client.complete_json(system_prompt="JSON", user_prompt="Default question")
    assert receipt.models == ["OpenAI / chat-choice"]
    assert [body["model"] for body in requests] == ["chat-choice", "legacy-default"]
    assert all(body["max_completion_tokens"] == 6000 for body in requests)
