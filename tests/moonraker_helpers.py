"""Offline ETX socket peer; all requests still pass through production framing."""

import asyncio
import json
from types import SimpleNamespace

from klipperai_agent.application.moonraker import MoonrakerMethods
from klipperai_agent.application.sessions import InMemorySessionStore
from klipperai_agent.domain.moonraker import MoonrakerObservation


def methods():
    return MoonrakerMethods(InMemorySessionStore(60), "/klipperai/", MoonrakerObservation())


async def until(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), 2)


class SocketPeer:
    def __init__(self, handler=None):
        self.reader = asyncio.StreamReader(limit=131072)
        self.sent = []
        self.closed = False
        self.handler = handler
        self.writer = SimpleNamespace(
            write=self.write, drain=self.drain, close=self.close, wait_closed=self.wait_closed
        )

    def feed(self, message):
        self.reader.feed_data(json.dumps({"jsonrpc": "2.0", **message}).encode() + b"\x03")

    def write(self, frame):
        assert frame.endswith(b"\x03")
        request = json.loads(frame[:-1])
        self.sent.append(request)
        if self.handler and "method" in request:
            response = self.handler(request)
            if response is not None:
                self.feed({"id": request["id"], **response})

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass

    async def connect(self, path):
        return self.reader, self.writer
