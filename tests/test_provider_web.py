import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import kai_agent.web.app as app_module
from kai_agent.application.providers import ProviderManagement
from kai_agent.domain.provider_settings import ProviderLimitError, ProviderPolicy
from kai_agent.runtime.settings import Settings
from tests.test_agent_integration import agent_service as agent_service
from tests.test_provider_management import store_at


@pytest.mark.parametrize(
    "base_url",
    ["https://printer.example", "http://192.168.1.22", "http://printer.local", "http://localhost"],
)
def test_provider_api_session_validation_secrecy_and_pending_restart(
    monkeypatch, tmp_path, agent_service, base_url
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
        lambda: Settings(data_dir=tmp_path / "data", root_path="/kai"),
    )
    monkeypatch.setattr(app_module, "build_container", lambda _: container)
    with TestClient(app_module.create_app(), base_url=base_url) as client:
        session = client.post("/api/ui-sessions").json()["session_id"]
        params = {"session_id": session}
        base = "/kai/api/providers"
        assert client.get(base, params={"session_id": "bad"}).status_code == 403
        assert (
            "provider-management" in client.get("/api/bootstrap", params=params).json()["features"]
        )
        status = client.get(base, params=params)
        assert status.headers["cache-control"] == "no-store"
        policy = status.json()["policy"]
        policy["provider"] = "openai"
        body = {**params, "revision": 0, "policy": policy, "api_key": "write-only-secret"}
        invalid = client.post(base + "/validate", json={**body, "session_id": "bad"})
        assert invalid.status_code == 403 and "write-only-secret" not in invalid.text
        cross_site = client.post(
            base + "/validate",
            json=body,
            headers={"origin": "https://evil.example", "sec-fetch-site": "cross-site"},
        )
        assert cross_site.status_code == 403 and "write-only-secret" not in cross_site.text
        validated = client.post(base + "/validate", json=body, headers={"origin": base_url})
        assert validated.status_code == 200 and "write-only-secret" not in validated.text
        assert manager.store.load()[0] == 0
        saved = client.put(base, json=body, headers={"origin": base_url})
        assert saved.status_code == 200 and saved.json()["restart_required"]
        assert b"write-only-secret" not in manager.store.path.read_bytes()
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
    from kai_agent.providers.responses import private_payload

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
