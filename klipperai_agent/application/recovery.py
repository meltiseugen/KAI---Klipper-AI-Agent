"""Resume public requests with fresh reads; never replay provider reasoning or tool calls."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar
from uuid import uuid4

from klipperai_agent.application.investigations import InvestigationMemory
from klipperai_agent.domain.investigation import Investigation, utc_now

T = TypeVar("T")
logger = logging.getLogger(__name__)


async def with_lease(
    memory: InvestigationMemory,
    record: Investigation,
    owner: str,
    operation: Awaitable[T],
    *,
    heartbeat_seconds: float = 10,
) -> T:
    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(heartbeat_seconds)
            await memory.checkpoint(record, owner)

    work = asyncio.ensure_future(operation)
    pulse = asyncio.create_task(heartbeat())
    try:
        done, _ = await asyncio.wait((work, pulse), return_when=asyncio.FIRST_COMPLETED)
        for completed in done:
            completed.result()
        return await work
    finally:
        work.cancel()
        pulse.cancel()
        await asyncio.gather(work, pulse, return_exceptions=True)
        await memory.release(owner)


class InvestigationRecovery:
    def __init__(
        self,
        memory: InvestigationMemory,
        resume: Callable[[Investigation, str], Awaitable[None]],
        *,
        poll_seconds: float = 10,
    ):
        self.memory = memory
        self.resume = resume
        self.poll_seconds = poll_seconds
        self.before = utc_now()
        self.task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            owner = str(uuid4())
            try:
                record = await self.memory.claim(owner, self.before)
                if record is not None:
                    await self.resume(record, owner)
                    continue
            except Exception:
                logger.exception("Investigation recovery failed; retrying after the lease expires.")
            await asyncio.sleep(self.poll_seconds)

    async def aclose(self) -> None:
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
