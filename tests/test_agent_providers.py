from __future__ import annotations

import json

import httpx
import pytest

from klipperai_agent.providers.responses import (
    OpenAIAgentModel,
    ProviderError,
    ResponsesClient,
)
from klipperai_agent.providers.web_search import OpenAIWebSearch


def client_for(data, *, status=200, key="test-key", requests=None):
    def handler(request):
        if requests is not None:
            requests.append(json.loads(request.content))
        return httpx.Response(status, json=data)

    return ResponsesClient("test-model", key, transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_responses_adapter_preserves_reasoning_and_function_calls():
    output = [
        {"type": "reasoning", "encrypted_content": "opaque", "summary": []},
        {"type": "function_call", "call_id": "call-1", "name": "inspect_config", "arguments": "{}"},
        {"type": "message", "content": [{"type": "output_text", "text": '{"response":"ok"}'}]},
    ]
    requests = []
    client = client_for({"status": "completed", "output": output}, requests=requests)
    try:
        turn = await OpenAIAgentModel(client).respond([{"role": "user", "content": "test"}], [])
        assert turn.output == output and turn.calls[0].call_id == "call-1"
        assert turn.text == '{"response":"ok"}'
        assert requests[0]["store"] is False
        assert requests[0]["include"] == ["reasoning.encrypted_content"]
        assert requests[0]["max_output_tokens"] == 6000
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data,status,key",
    [
        ({}, 200, None),
        ({}, 401, "bad"),
        ({"status": "incomplete", "output": []}, 200, "test"),
        ({"status": "completed", "output": {}}, 200, "test"),
        ({"status": "completed", "output": [None]}, 200, "test"),
        ([], 200, "test"),
    ],
)
async def test_responses_adapter_rejects_failed_and_malformed_responses(data, status, key):
    client = client_for(data, status=status, key=key)
    try:
        with pytest.raises(ProviderError):
            await client.create(input="test")
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output",
    [
        [{"type": "function_call", "name": "unknown"}],
        [{"type": "message", "content": [{"type": "refusal", "refusal": "No"}]}],
    ],
)
async def test_agent_model_rejects_invalid_calls_and_refusals(output):
    client = client_for({"status": "completed", "output": output})
    try:
        with pytest.raises(ProviderError):
            await OpenAIAgentModel(client).respond([], [])
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_web_search_only_sends_query_and_validates_citation_links():
    annotations = [
        {"type": "url_citation", "url": "https://www.klipper3d.org/FAQ.html", "title": "FAQ"},
        {"type": "url_citation", "url": "https://www.klipper3d.org/FAQ.html"},
        {"type": "url_citation", "url": "javascript:alert(1)"},
        {"type": "url_citation", "url": "https://user:pass@example.com"},
    ]
    output = [
        {"type": "web_search_call"},
        {
            "type": "message",
            "content": [
                {"type": "other"},
                {"type": "output_text", "text": "Guidance", "annotations": annotations},
            ],
        },
    ]
    requests = []
    client = client_for({"status": "completed", "output": output}, requests=requests)
    try:
        result = await OpenAIWebSearch(client, "klipper3d.org, docs.kalico.gg").search(
            "Timer too close"
        )
        assert result.summary == "Guidance" and len(result.citations) == 1
        assert requests[0]["input"] == "Timer too close"
        assert requests[0]["max_tool_calls"] == 1
        assert requests[0]["tools"][0]["filters"]["allowed_domains"] == [
            "klipper3d.org",
            "docs.kalico.gg",
        ]
    finally:
        await client.aclose()
    client = client_for({"status": "completed", "output": []})
    try:
        assert (
            await OpenAIWebSearch(client).search("Klipper")
        ).summary == "No search summary was returned."
    finally:
        await client.aclose()
