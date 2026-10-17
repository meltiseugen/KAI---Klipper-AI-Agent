"""Small Moonraker-facing API; no prompts, credentials or printer commands."""

from __future__ import annotations

import time
from collections import deque

from klipperai_agent.application.sessions import InMemorySessionStore
from klipperai_agent.domain.moonraker import MoonrakerObservation, RemoteMethodError, capabilities


class MoonrakerMethods:
    def __init__(self, sessions: InMemorySessionStore, root_path: str, state: MoonrakerObservation):
        self.sessions = sessions
        self.root_path = root_path.rstrip("/")
        self.state = state
        self._created: deque[float] = deque()

    async def dispatch(self, method: str, params: object) -> dict:
        if method not in capabilities()["methods"]:
            raise RemoteMethodError(-32601, "Unknown KlipperAI method.")
        if params is not None and params != {}:
            raise RemoteMethodError(-32602, "This method accepts no arguments.")
        if method == "klipperai.capabilities":
            return capabilities()
        if method == "klipperai.status":
            return self.state.snapshot()
        now = time.monotonic()
        while self._created and self._created[0] <= now - 60:
            self._created.popleft()
        if len(self._created) >= 10:
            raise RemoteMethodError(-32000, "Session bootstrap rate limit reached.")
        self._created.append(now)
        session = self.sessions.create()
        return {
            "session_id": session.session_id,
            "embed_path": f"{self.root_path}/embed?session={session.session_id}",
            "expires_at": session.expires_at.isoformat(),
        }
