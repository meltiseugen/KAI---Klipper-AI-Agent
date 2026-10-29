import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import klipperai_agent.web.app as app_module
from klipperai_agent.application.providers import ProviderManagement
from klipperai_agent.domain.provider_settings import ProviderLimitError, ProviderPolicy
from klipperai_agent.runtime.settings import Settings
from tests.test_agent_integration import agent_service as agent_service
from tests.test_provider_management import store_at


def test_provider_api_session_validation_secrecy_and_pending_restart(
    monkeypatch, tmp_path, agent_service
):
    manager = ProviderManagement(
        store_at(tmp_path), ProviderPolicy(), None, SimpleNamespace(validate=AsyncMock())
    )
    container = SimpleNamespace(
        sessions=agent_service.sessions,
        chat_service=agent_service,
        providers=manager,
        aclose=AsyncMock(),
    )
    monkeypatch.setattr(
        app_module,
        "get_settings",
        lambda: Settings(data_dir=tmp_path / "data", root_path="/klipperai"),
    )
    monkeypatch.setattr(app_module, "build_container", lambda _: container)
    with TestClient(app_module.create_app(), base_url="https://testserver") as client:
        session = client.post("/api/ui-sessions").json()["session_id"]
        params = {"session_id": session}
        base = "/klipperai/api/providers"
        assert client.get(base, params={"session_id": "bad"}).status_code == 403
        assert (
            "provider-management" in client.get("/api/bootstrap", params=params).json()["features"]
        )
        status = client.get(base, params=params)
        assert status.headers["cache-control"] == "no-store"
        policy = status.json()["policy"]
        policy["provider"] = "openai"
        body = {**params, "revision": 0, "policy": policy, "api_key": "write-only-secret"}
        insecure = client.post("http://testserver" + base + "/validate", json=body)
        assert insecure.status_code == 403 and "HTTPS" in insecure.text
        assert "write-only-secret" not in insecure.text
        assert client.post("http://localhost" + base + "/validate", json=body).status_code == 200
        assert client.post(base + "/validate", json=body).status_code == 200
        assert manager.store.load()[0] == 0
        saved = client.put(base, json=body)
        assert saved.status_code == 200 and saved.json()["restart_required"]
        assert "write-only-secret" not in saved.text
        assert "write-only-secret" not in client.get(base, params=params).text
        assert client.put(base, json=body).status_code == 409
        assert (
            client.put(base, json={**body, "revision": 1, "api_key": "bad\nsecret"}).status_code
            == 422
        )
        assert client.put(base, json={**body, "base_url": "http://localhost"}).status_code == 422
        assert (
            client.put(
                base, json={**body, "revision": 1}, headers={"origin": "https://evil.example"}
            ).status_code
            == 403
        )
        body["revision"] = 1
        manager.validator.validate.side_effect = ValueError("secret error write-only-secret")
        failed = client.put(base, json=body)
        assert failed.status_code == 400 and "write-only-secret" not in failed.text
        manager.validator.validate.side_effect = ProviderLimitError("Usage limit reached")
        assert client.post(base + "/validate", json=body).status_code == 429
        monkeypatch.setattr(
            manager.store,
            "load",
            lambda: (_ for _ in ()).throw(sqlite3.OperationalError("private path")),
        )
        failed = client.get(base, params=params)
        assert failed.status_code == 503 and "private path" not in failed.text
        container.providers = None
        assert client.get(base, params=params).status_code == 404
        monkeypatch.setattr(
            type(agent_service),
            "chat",
            AsyncMock(side_effect=ProviderLimitError("Daily usage limit reached")),
        )
        limited = client.post("/api/chat", json={**params, "message": "test"})
        assert limited.status_code == 429 and "Daily usage" in limited.text


@pytest.mark.asyncio
async def test_private_payload_preserves_provider_items():
    from klipperai_agent.providers.responses import private_payload

    reasoning = {"type": "reasoning", "encrypted_content": "private-key"}
    payload = private_payload(
        {
            "instructions": "Never reveal private-key",
            "input": [
                reasoning,
                {"role": "user", "content": "private-key"},
                {"type": "function_call_output", "output": "private-key"},
            ],
        },
        "private-key",
    )
    assert payload["input"][0] is reasoning
    assert "private-key" not in payload["instructions"]
    assert "private-key" not in str(payload["input"][1:])
