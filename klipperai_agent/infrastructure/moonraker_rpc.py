"""Bounded JSON-RPC over Moonraker's ETX-delimited local Unix socket."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import Any, Awaitable, Callable

from klipperai_agent.domain.moonraker import RemoteMethodError


class RpcError(RuntimeError):
    """Sanitized transport or remote protocol failure."""


class MoonrakerRpc:
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        dispatch: Callable[[str, object], Awaitable[dict]],
        notify: Callable[[str, object], None],
        *,
        timeout: float = 10,
    ):
        self.reader, self.writer = reader, writer
        self.dispatch, self.notify = dispatch, notify
        self.timeout = timeout
        self._next_id = 0
        self._pending: dict[str, asyncio.Future] = {}
        self._write_lock = asyncio.Lock()
        self._closing = False
        self.task = asyncio.create_task(self._read())

    async def send(self, payload: dict) -> None:
        async with self._write_lock:
            self.writer.write(json.dumps(payload, allow_nan=False).encode() + b"\x03")
            await self._bounded(self.writer.drain())

    async def _bounded(self, operation: Awaitable[Any]) -> Any:
        # asyncio.wait_for can lose external cancellation in Python 3.10 when
        # an operation completes concurrently. wait preserves that cancellation.
        task = asyncio.ensure_future(operation)
        try:
            done, _ = await asyncio.wait({task}, timeout=self.timeout)
            if not done:
                raise asyncio.TimeoutError
            return task.result()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def call(self, method: str, params: dict | None = None) -> Any:
        if self.task.done():
            raise RpcError("Moonraker connection is closed.")
        self._next_id += 1
        identifier = f"kai-{self._next_id}"
        future = asyncio.get_running_loop().create_future()
        self._pending[identifier] = future
        try:
            await self.send(
                {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params or {}}
            )
            return await self._bounded(future)
        finally:
            self._pending.pop(identifier, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()

    async def _read(self) -> None:
        try:
            while not self._closing:
                frame = await self.reader.readuntil(b"\x03")
                message = json.loads(frame[:-1])
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    raise RpcError("Invalid Moonraker protocol message.")
                method = message.get("method")
                identifier = message.get("id")
                if isinstance(method, str):
                    if "id" not in message:
                        self.notify(method, message.get("params"))
                    elif isinstance(identifier, (int, str)) and not isinstance(identifier, bool):
                        await self._reply(identifier, method, message.get("params"))
                elif isinstance(identifier, str) and identifier in self._pending:
                    future = self._pending[identifier]
                    if not future.done():
                        if "error" in message or "result" not in message:
                            future.set_exception(
                                RpcError("Moonraker rejected the integration request.")
                            )
                        else:
                            future.set_result(message["result"])
        except (
            OSError,
            ValueError,
            RecursionError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
        ) as exc:
            raise RpcError("Moonraker socket disconnected or sent an invalid frame.") from exc
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(RpcError("Moonraker socket disconnected."))

    async def _reply(self, identifier: int | str, method: str, params: object) -> None:
        try:
            result = await self.dispatch(method, params)
            response = {"result": result}
        except RemoteMethodError as exc:
            response = {"error": {"code": exc.code, "message": str(exc)}}
        except Exception:
            response = {"error": {"code": -32603, "message": "KlipperAI method failed."}}
        await self.send({"jsonrpc": "2.0", "id": identifier, **response})

    async def aclose(self) -> None:
        # Stop new reader iterations before closing the transport.
        self._closing = True
        self.writer.close()
        self.task.cancel()
        with suppress(asyncio.CancelledError, RpcError, OSError):
            await self.task
        with suppress(OSError, asyncio.TimeoutError):
            await self._bounded(self.writer.wait_closed())
