from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import klipperai_agent.web.app as app_module
from klipperai_agent.runtime.settings import Settings


class _FakeMoonraker:
    async def ping(self) -> bool:
        return True


class _FakeChatService:
    async def create_ui_session(self):
        return {
            "session_id": "session-1",
            "embed_path": "/embed?session=session-1",
            "expires_at": datetime(2030, 1, 1, tzinfo=timezone.utc),
        }

    async def bootstrap(self, session_id: str):
        if session_id == "bad":
            raise ValueError("bad session")
        return {
            "session_id": session_id,
            "provider": "stub",
            "moonraker_reachable": True,
            "klipper_reachable": True,
            "expires_at": datetime(2030, 1, 1, tzinfo=timezone.utc),
            "features": [],
        }

    async def chat(self, payload):
        if payload.message == "bad":
            raise ValueError("bad session")
        return {
            "session_id": payload.session_id,
            "thread_id": "thread-1",
            "response": "ok",
            "findings": [],
            "next_actions": [],
            "provider": "stub",
            "moonraker_reachable": True,
        }


class _FakeContainer:
    def __init__(self) -> None:
        self.moonraker = _FakeMoonraker()
        self.chat_service = _FakeChatService()
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def test_create_app_serves_ui_api_and_lifespan(monkeypatch, tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        checkpoint_db=tmp_path / "data" / "checkpoints.sqlite",
        printer_data_root=tmp_path / "printer_data",
    )
    container = _FakeContainer()

    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(app_module, "build_container", lambda _settings: container)

    application = app_module.create_app()
    with TestClient(application) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert root.headers["cache-control"] == "no-store"
        assert "<!DOCTYPE html>" in root.text

        direct = client.get("/direct")
        assert direct.status_code == 200
        assert direct.headers["cache-control"] == "no-store"

        assert client.get("/healthz").json() == {"status": "ok", "moonraker_reachable": True}
        assert client.post("/api/ui-sessions").json()["session_id"] == "session-1"
        assert client.get("/api/bootstrap", params={"session_id": "session-1"}).status_code == 200
        assert client.get("/api/bootstrap", params={"session_id": "bad"}).status_code == 403

        chat_payload = {"session_id": "session-1", "message": "hello", "artifacts": []}
        assert client.post("/api/chat", json=chat_payload).json()["response"] == "ok"
        chat_payload["message"] = "bad"
        assert client.post("/api/chat", json=chat_payload).status_code == 403

        embed = client.get("/embed", params={"session": "hinted"})
        assert embed.status_code == 200
        assert embed.headers["cache-control"] == "no-store"
        assert "hinted" in embed.text

    assert container.closed is True


def test_container_lookup() -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    with pytest.raises(RuntimeError, match="not initialized"):
        app_module._get_container(request)

    expected = object()
    request.app.state.container = expected
    assert app_module._get_container(request) is expected
