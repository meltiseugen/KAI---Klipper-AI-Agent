"""One shared guard for agent, search, research and compatibility requests."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from klipperai_agent.domain.provider_settings import (
    ProviderLimitError,
    ProviderPolicy,
    ProviderRepository,
)


class UsageGuard:
    def __init__(self, store: ProviderRepository, policy: ProviderPolicy):
        self.store = store
        self.policy = policy
        self.active = 0

    @asynccontextmanager
    async def request(
        self, payload: dict[str, Any], output_tokens: int
    ) -> AsyncIterator[tuple[str, int]]:
        if self.active >= self.policy.max_concurrent_requests:
            raise ProviderLimitError("Too many provider requests are already running.")
        # UTF-8 bytes plus framing/output reserve is deliberately conservative.
        # Hosted search context is provider-owned; this is not an invoice estimate.
        tokens = len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) + 1024 + output_tokens
        reservation = self.store.reserve(self.policy, tokens)
        self.active += 1
        try:
            yield reservation
        finally:
            self.active -= 1

    def record(self, reservation: tuple[str, int], data: Any) -> None:
        usage = data.get("usage") if isinstance(data, dict) else None
        total = usage.get("total_tokens") if isinstance(usage, dict) else None
        if type(total) is int and total >= 0:
            self.store.settle(reservation, total)

    def throttle(self, retry_after: str) -> None:
        try:
            delay = float(retry_after)
        except ValueError:
            delay = 60.0
        self.store.cooldown(max(1, min(3600, delay)))
