"""Reconnectable local Moonraker extension with a fixed subscription and metadata key."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path
from typing import Awaitable, Callable

from klipperai_agent.domain.moonraker import (
    AGENT_NAME,
    AGENT_URL,
    AGENT_VERSION,
    SUBSCRIPTIONS,
    MoonrakerExtension,
    MoonrakerObservation,
    capabilities,
)
from klipperai_agent.infrastructure.moonraker_rpc import MoonrakerRpc, RpcError


async def open_moonraker_socket(path: Path) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    connect = getattr(asyncio, "open_unix_connection", None)
    if connect is None:
        raise NotImplementedError("Local Moonraker sockets require Unix socket support.")
    return await asyncio.wait_for(connect(str(path), limit=131072), 10)


class MoonrakerAgent:
    def __init__(
        self,
        socket_path: Path,
        methods: MoonrakerExtension,
        *,
        connector: Callable[
            [Path], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]
        ] = open_moonraker_socket,
        retry_seconds: float = 1,
        heartbeat_seconds: float = 30,
    ):
        self.socket_path, self.methods = socket_path, methods
        self.state: MoonrakerObservation = methods.state
        self.connector = connector
        self.retry_seconds, self.heartbeat_seconds = retry_seconds, heartbeat_seconds
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._generation = 0
        self._subscribing = False
        self._updates: list[list] = []
        self._stopped = False

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopped = False
            self._task = asyncio.create_task(self._run())

    async def aclose(self) -> None:
        self._stopped = True
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self.state.disconnect()

    def _notify(self, method: str, params: object) -> None:
        if method == "notify_status_update" and (self.state.subscribed or self._subscribing):
            if not isinstance(params, list) or len(params) != 2:
                raise ValueError("Invalid status update.")
            if self._subscribing:
                if len(self._updates) >= 32:
                    raise ValueError("Subscription update buffer overflow.")
                self._updates.append(params)
            else:
                self.state.update(params[0], params[1])
        elif method in {
            "notify_klippy_ready",
            "notify_klippy_shutdown",
            "notify_klippy_disconnected",
        }:
            self.state.subscribed = False
            self._generation += 1
            self._updates.clear()
            self.state.eventtime = None
            self.state.klippy_state = {
                "notify_klippy_ready": "ready",
                "notify_klippy_shutdown": "shutdown",
                "notify_klippy_disconnected": "disconnected",
            }[method]
            self.state.revision += 1
            self._wake.set()

    async def _run(self) -> None:
        delay = self.retry_seconds
        while not self._stopped:
            peer = None
            try:
                reader, writer = await self.connector(self.socket_path)
                peer = MoonrakerRpc(reader, writer, self.methods.dispatch, self._notify)
                await self._session(peer)
            except (OSError, ValueError, RpcError, asyncio.TimeoutError, NotImplementedError):
                self.state.disconnect()
            finally:
                if peer:
                    await peer.aclose()
            if not self._stopped:
                await asyncio.sleep(delay)
                delay = min(30, max(self.retry_seconds, delay * 2))

    async def _session(self, peer: MoonrakerRpc) -> None:
        self._wake.clear()
        await peer.call(
            "server.connection.identify",
            {
                "client_name": AGENT_NAME,
                "version": AGENT_VERSION,
                "type": "agent",
                "url": AGENT_URL,
            },
        )
        self.state.connected = self.state.registered = True
        self.state.error = None
        self.state.revision += 1
        try:
            await peer.call(
                "server.database.post_item",
                {
                    "namespace": "klipperai",
                    "key": "integration",
                    "value": capabilities(),
                },
            )
            self.state.metadata_registered = True
        except RpcError:
            self.state.error = "Moonraker metadata namespace is unavailable."
        await peer.call(
            "connection.send_event", {"event": "klipperai_ready", "data": capabilities()}
        )
        while not self._stopped:
            self._wake.clear()
            await self._refresh(peer)
            wake = asyncio.create_task(self._wake.wait())
            try:
                await asyncio.wait(
                    {peer.task, wake},
                    timeout=self.heartbeat_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if peer.task.done():
                    await peer.task
            finally:
                wake.cancel()
                with suppress(asyncio.CancelledError):
                    await wake

    async def _refresh(self, peer: MoonrakerRpc) -> None:
        generation = self._generation
        info = await peer.call("server.info")
        if generation != self._generation:
            return
        if not isinstance(info, dict):
            raise RpcError("Invalid Moonraker server info.")
        value = info.get("klippy_state")
        self.state.klippy_state = (
            value
            if value in ("ready", "startup", "shutdown", "error", "disconnected")
            else "unknown"
        )
        if self.state.klippy_state != "ready":
            self.state.subscribed = False
        elif not self.state.subscribed:
            try:
                available = await peer.call("printer.objects.list")
                if not isinstance(available, dict) or not isinstance(
                    available.get("objects"), list
                ):
                    raise RpcError("Invalid object list.")
                objects = {
                    name: fields
                    for name, fields in SUBSCRIPTIONS.items()
                    if name in available["objects"]
                }
                self._subscribing = True
                result = await peer.call("printer.objects.subscribe", {"objects": objects})
                if generation != self._generation:
                    return
                if not isinstance(result, dict):
                    raise RpcError("Invalid subscription response.")
                self.state.update(result.get("status"), result.get("eventtime"), initial=True)
                for update in self._updates:
                    self.state.update(update[0], update[1])
                self.state.subscribed = bool(objects)
                if self.state.metadata_registered:
                    self.state.error = None
            except RpcError:
                self.state.error = "Printer subscription unavailable; retrying."
            finally:
                self._subscribing = False
                self._updates.clear()
        self.state.revision += 1
