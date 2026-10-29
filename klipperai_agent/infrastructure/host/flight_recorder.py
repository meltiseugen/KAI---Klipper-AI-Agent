"""Opt-in sampler owned by application lifespan, never started by model tools."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import sqlite3
import sys

from klipperai_agent.diagnostics.host_history import summarize_history
from klipperai_agent.infrastructure.host.history_store import HostHistoryStore
from klipperai_agent.infrastructure.host.proc import ProcSampler

logger = logging.getLogger(__name__)


class HostFlightRecorder:
    def __init__(self, store: HostHistoryStore, interval_seconds: float = 10):
        self.store = store
        self.interval_seconds = interval_seconds
        self.sampler = ProcSampler()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.error: str | None = None

    def start(self) -> None:
        if self._task is not None:
            return
        if sys.platform != "linux":
            self.error = (
                "Host flight recording requires Linux /proc; no samples collected on this host."
            )
            return
        self.sampler.ticks = int(os.sysconf("SC_CLK_TCK"))
        self.sampler.page_kib = int(os.sysconf("SC_PAGE_SIZE")) // 1024
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def aclose(self) -> None:
        self._stop.set()
        if self._task is not None:
            # Finish a bounded in-progress write instead of abandoning a worker thread.
            await self._task
            self._task = None

    def _record(self) -> None:
        self.store.append(self.sampler.sample())

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self._record)
                self.error = None
            except (OSError, ValueError, sqlite3.Error):
                self.error = (
                    "Host flight recorder could not collect/store a sample; history may have gaps."
                )
                logger.warning(self.error)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                pass

    def read_window(self, stamp: float | None) -> dict:
        if stamp is None or not math.isfinite(stamp) or not 946684800 <= stamp <= 4102444800:
            return {
                "notes": ["No usable incident clock anchor; flight history cannot be correlated."]
            }
        try:
            result = summarize_history(self.store.window(stamp), stamp)
        except (OSError, ValueError, sqlite3.Error):
            return {"notes": ["Retained host flight history unavailable or malformed."]}
        if self.error:
            result["notes"].append(self.error)
        return result
