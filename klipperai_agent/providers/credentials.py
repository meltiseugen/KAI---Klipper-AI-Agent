"""Non-generating credential and model-access checks at the fixed OpenAI origin."""

from __future__ import annotations

import httpx

from klipperai_agent.providers.usage import UsageGuard


class OpenAICredentialValidator:
    def __init__(self, guard: UsageGuard, transport: httpx.AsyncBaseTransport | None = None):
        self.guard = guard
        self.transport = transport

    async def validate(self, key: str, models: list[str]) -> None:
        async with httpx.AsyncClient(timeout=15, transport=self.transport) as client:
            for model in models:
                self.guard.store.reserve(self.guard.policy, 0)
                try:
                    response = await client.get(
                        f"https://api.openai.com/v1/models/{model}",
                        headers={"Authorization": f"Bearer {key}"},
                    )
                    if response.status_code == 429:
                        self.guard.throttle(response.headers.get("retry-after", "60"))
                        raise ValueError("OpenAI rate limit reached. Wait before validating again.")
                    if response.status_code in (401, 403):
                        raise ValueError("OpenAI rejected the key or its model-read permission.")
                    if response.status_code == 404:
                        raise ValueError(
                            "A configured model is unavailable to this key. Check model IDs."
                        )
                    response.raise_for_status()
                    data = response.json()
                    if not isinstance(data, dict) or data.get("id") != model:
                        raise ValueError("OpenAI returned an unexpected model-access response.")
                except httpx.HTTPError:
                    raise ValueError("Could not reach OpenAI to validate model access.") from None
