from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import klipperai_agent.web.app as app_module
from klipperai_agent.domain.provider_settings import ProviderPolicy
from klipperai_agent.runtime.settings import Settings
from tests.test_agent_integration import agent_service as agent_service


@pytest.fixture
def embedded_client(monkeypatch, tmp_path, agent_service):
    manager = SimpleNamespace(active_policy=ProviderPolicy(provider="openai"), active_key=None)
    container = SimpleNamespace(
        sessions=agent_service.sessions,
        chat_service=agent_service,
        providers=manager,
        aclose=AsyncMock(),
    )
    monkeypatch.setattr(
        app_module,
        "get_settings",
        lambda: Settings(data_dir=tmp_path / "data", root_path="/printer"),
    )
    monkeypatch.setattr(app_module, "build_container", lambda _: container)
    with TestClient(app_module.create_app()) as client:
        session = client.post("/printer/api/ui-sessions").json()["session_id"]
        yield client, session, manager


def test_provider_readiness_requires_a_key_for_all_chat_requests(embedded_client):
    client, session, manager = embedded_client
    params = {"session_id": session}
    response = client.get("/printer/api/bootstrap", params=params)
    assert response.json()["provider_configured"] is False
    for endpoint in ("chat", "chat/stream"):
        response = client.post(f"/printer/api/{endpoint}", json={**params, "message": "Check logs"})
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "provider_not_configured"
    for endpoint in ("chat", "chat/stream"):
        response = client.post(
            f"/printer/api/{endpoint}", json={"session_id": "expired", "message": "Check logs"}
        )
        assert response.status_code == 403
    manager.active_key = "private-provider-key"
    response = client.get("/printer/api/bootstrap", params=params)
    assert response.json()["provider_configured"] is True
    assert "private-provider-key" not in response.text
    manager.active_key = None
    assert (
        client.get("/printer/api/bootstrap", params=params).json()["provider_configured"] is False
    )
    for endpoint in ("chat", "chat/stream"):
        for message in ("Check logs", "Audit active configuration", "Generate a status macro"):
            response = client.post(f"/printer/api/{endpoint}", json={**params, "message": message})
            assert response.status_code == 503


def test_text_attachments_reach_chat_and_stream_with_same_limits(embedded_client):
    client, session, manager = embedded_client
    manager.active_key = "fixture"
    artifact = {
        "kind": "klippy_log",
        "label": "klippy.log",
        "content": "Lost communication with MCU",
    }
    for endpoint in ("chat", "chat/stream"):
        response = client.post(
            f"/printer/api/{endpoint}",
            json={"session_id": session, "message": "Which firmware?", "artifacts": [artifact]},
        )
        assert response.status_code == 200
        assert "Your saved firmware is Kalico." in response.text
    # Boundary sizes are accepted without truncation.
    from klipperai_agent.contracts.api import ChatRequest

    request = ChatRequest(
        session_id=session, message="Analyze", artifacts=[{**artifact, "content": "x" * 40000}] * 4
    )
    assert sum(len(item.content) for item in request.artifacts) == 160000


@pytest.mark.parametrize(
    "artifacts",
    [
        [{"content": "a"}] * 9,
        [{"content": "a" * 40001}],
        [{"content": "a" * 40000}] * 5,
        [{"content": " \r\n\t"}],
        [{"content": "binary\x00secret"}],
        [{"content": "\ufffdsecret"}],
        [{"label": "x" * 121, "content": "secret"}],
        [{"kind": "arbitrary_file", "content": "secret"}],
    ],
)
def test_invalid_attachments_are_rejected_without_echoing_content(embedded_client, artifacts):
    client, session, _ = embedded_client
    for endpoint in ("chat", "chat/stream"):
        response = client.post(
            f"/printer/api/{endpoint}",
            json={"session_id": session, "message": "Analyze", "artifacts": artifacts},
        )
        assert response.status_code == 422
        assert response.json() == {
            "detail": "Invalid request. Check the required fields and their values."
        }
