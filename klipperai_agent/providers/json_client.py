from __future__ import annotations

from contextlib import nullcontext
from typing import Any

import httpx

from klipperai_agent.domain.provider_settings import ModelProfile
from klipperai_agent.domain.redaction import redact_text
from klipperai_agent.providers.normalization import _parse_json_object
from klipperai_agent.providers.usage import UsageGuard


class OpenAIJsonClient:
    def __init__(
        self,
        model: str,
        api_key: str | None,
        *,
        guard: UsageGuard | None = None,
        profile: ModelProfile | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._guard = guard
        self._profile = profile or ModelProfile(model=model)

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        if not self._api_key:
            raise ValueError("OpenAI provider selected but no API key is configured.")

        payload: dict[str, Any] = {
            "model": self._profile.model,
            "max_completion_tokens": self._profile.max_output_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": redact_text(user_prompt, (self._api_key,))},
            ],
            "response_format": {"type": "json_object"},
        }
        if self._profile.reasoning_effort != "default":
            payload["reasoning_effort"] = self._profile.reasoning_effort
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with (
                self._guard.request(payload, self._profile.max_output_tokens)
                if self._guard
                else nullcontext(None) as reservation
            ):
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if self._guard and response.status_code == 429:
                    self._guard.throttle(response.headers.get("retry-after", "60"))
                response.raise_for_status()
                data = response.json()
                if self._guard and reservation is not None:
                    self._guard.record(reservation, data)

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return _parse_json_object(str(content))
