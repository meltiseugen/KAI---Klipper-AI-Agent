"""Cancellation-safe nested deadlines on Python 3.10 as well as newer hosts."""

import asyncio
from typing import Awaitable, TypeVar

T = TypeVar("T")


async def within(awaitable: Awaitable[T], seconds: float) -> T:
    task = asyncio.ensure_future(awaitable)
    try:
        done, _ = await asyncio.wait({task}, timeout=seconds)
        if not done:
            raise asyncio.TimeoutError
        return task.result()
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
