from __future__ import annotations

from typing import Any

import httpx

from klipperai_agent.providers.normalization import _parse_json_object


class OpenAIJsonClient:
    def __init__(self, model: str, api_key: str | None) -> None:
        self._model = model
        self._api_key = api_key

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        if not self._api_key:
            raise ValueError("OpenAI provider selected but no API key is configured.")

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()

        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return _parse_json_object(str(content))
