"""SSE transport for public action events and the final typed response."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import AsyncIterator

from klipperai_agent.application.chat import ChatService
from klipperai_agent.contracts.api import ChatRequest
from klipperai_agent.domain.evidence import AgentEvent


class ChatEventStream:
    def __init__(self, service: ChatService, heartbeat_seconds: float = 15.0) -> None:
        self._service = service
        self._heartbeat_seconds = heartbeat_seconds

    async def events(self, payload: ChatRequest) -> AsyncIterator[str]:
        queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()

        async def on_event(event: AgentEvent) -> None:
            await queue.put(("agent", event.model_dump()))

        async def produce() -> None:
            try:
                result = await self._service.chat(payload, on_event=on_event)
                await queue.put(("result", result.model_dump()))
            except Exception:
                await queue.put(
                    ("error", {"message": "The investigation failed. Please try again."})
                )
            finally:
                await queue.put(None)

        task = asyncio.create_task(produce())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=self._heartbeat_seconds)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    break
                name, data = item
                yield f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        finally:
            # Disconnecting the browser must also stop provider calls and tool dispatch.
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
