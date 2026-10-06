"""Small Responses API adapter with an application-owned HTTP lifetime."""

from __future__ import annotations

from typing import Any

import httpx

from klipperai_agent.agent.models import ModelTurn, ToolCall


class ProviderError(RuntimeError):
    """The provider failed or returned an unusable protocol message."""


class ResponsesClient:
    def __init__(
        self,
        model: str,
        api_key: str | None,
        *,
        max_output_tokens: int = 6000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._max_output_tokens = max_output_tokens
        self._http = httpx.AsyncClient(timeout=60.0, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def create(self, **payload: Any) -> list[dict[str, Any]]:
        if not self._api_key:
            raise ProviderError("No OpenAI API key is configured.")
        try:
            response = await self._http.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "store": False,
                    "max_output_tokens": self._max_output_tokens,
                    **payload,
                },
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(
                "OpenAI request failed; check credentials, connectivity and model support."
            ) from exc
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
