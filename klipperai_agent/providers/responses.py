"""Small Responses API adapter with an application-owned HTTP lifetime."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

import httpx

from klipperai_agent.agent.models import ModelTurn, ToolCall
from klipperai_agent.domain.provider_settings import ModelProfile, ProviderPolicy
from klipperai_agent.domain.redaction import redact_data, redact_text
from klipperai_agent.providers.usage import UsageGuard


class ProviderError(RuntimeError):
    """The provider failed or returned an unusable protocol message."""


def private_payload(payload: dict[str, Any], key: str) -> dict[str, Any]:
    body = dict(payload)
    if isinstance(body.get("instructions"), str):
        body["instructions"] = redact_text(body["instructions"], (key,))
    value = body.get("input")
    if isinstance(value, str):
        body["input"] = redact_text(value, (key,))
    elif isinstance(value, list):
        # Provider output (especially encrypted reasoning) must round-trip verbatim.
        body["input"] = [
            redact_data(item, (key,))
            if isinstance(item, dict)
            and (item.get("role") == "user" or item.get("type") == "function_call_output")
            else item
            for item in value
        ]
    return body


class ResponsesClient:
    def __init__(
        self,
        model: str,
        api_key: str | None,
        *,
        max_output_tokens: int = 6000,
        transport: httpx.AsyncBaseTransport | None = None,
        guard: UsageGuard | None = None,
        policy: ProviderPolicy | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._max_output_tokens = max_output_tokens
        self._http = httpx.AsyncClient(timeout=60.0, transport=transport)
        self._guard = guard
        self._policy = policy

    async def aclose(self) -> None:
        await self._http.aclose()

    async def create(self, *, purpose: str = "agent", **payload: Any) -> list[dict[str, Any]]:
        if not self._api_key:
            raise ProviderError("No OpenAI API key is configured.")
        if purpose not in {"agent", "search", "knowledge"}:
            raise ProviderError("Unknown provider route.")
        profile = (
            getattr(self._policy, purpose)
            if self._policy
            else ModelProfile(model=self._model, max_output_tokens=self._max_output_tokens)
        )
        limit = min(
            payload.get("max_output_tokens", profile.max_output_tokens), profile.max_output_tokens
        )
        body = {
            **private_payload(payload, self._api_key),
            "model": profile.model,
            "store": False,
            "max_output_tokens": limit,
        }
        if profile.reasoning_effort != "default":
            body["reasoning"] = {"effort": profile.reasoning_effort}
        try:
            async with (
                self._guard.request(body, limit)
                if self._guard
                else nullcontext(None) as reservation
            ):
                response = await self._http.post(
                    "https://api.openai.com/v1/responses",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=body,
                )
                if response.status_code == 429 and self._guard:
                    self._guard.throttle(response.headers.get("retry-after", "60"))
                response.raise_for_status()
                data = response.json()
                if self._guard and reservation is not None:
                    self._guard.record(reservation, data)
        except (httpx.HTTPError, ValueError):
            raise ProviderError(
                "OpenAI request failed; check credentials, connectivity and model support."
            ) from None
        if not isinstance(data, dict) or data.get("status") != "completed":
            raise ProviderError("OpenAI did not complete the response.")
        output = data.get("output")
        if not isinstance(output, list) or not all(isinstance(item, dict) for item in output):
            raise ProviderError("OpenAI returned an invalid output list.")
        return output


class OpenAIAgentModel:
    def __init__(self, client: ResponsesClient) -> None:
        self._client = client

    async def respond(
        self,
        conversation: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelTurn:
        output = await self._client.create(
            input=conversation,
            tools=tools,
            parallel_tool_calls=False,
            include=["reasoning.encrypted_content"],
            text={"format": {"type": "json_object"}},
        )
        calls: list[ToolCall] = []
        text: list[str] = []
        for item in output:
            if item.get("type") == "function_call":
                if not all(
                    isinstance(item.get(key), str) and item[key]
                    for key in ("call_id", "name", "arguments")
                ):
                    raise ProviderError("Invalid function call returned by OpenAI.")
                calls.append(ToolCall(item["call_id"], item["name"], item["arguments"]))
            elif item.get("type") == "message":
                for part in item.get("content", []):
                    if part.get("type") == "refusal":
                        raise ProviderError("The provider declined this request.")
                    if part.get("type") == "output_text":
                        text.append(part["text"])
        return ModelTurn(output=output, calls=calls, text="\n".join(text))
