import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

import klipperai_agent.web.app as app_module
import klipperai_agent.web.moonraker as routes_module
from klipperai_agent.domain.moonraker import MoonrakerObservation
from klipperai_agent.runtime.settings import Settings
from tests.test_agent_integration import agent_service as agent_service


@pytest.mark.asyncio
async def test_status_stream_coalesces_heartbeats_updates_and_session_expiry():
    state = MoonrakerObservation()
    valid = [True]
    stream = routes_module.status_events(state, lambda: valid[0], interval=0)
    first = await anext(stream)
    assert first.startswith("event: status\ndata: ")
    assert json.loads(first.split("data: ", 1)[1])["stale"]
    assert await anext(stream) == ": heartbeat\n\n"
    state.connected = state.subscribed = True
    state.update({"print_stats": {"state": "printing"}}, 1)
    state.update({"print_stats": {"state": "paused"}}, 2)
    assert '"paused"' in await anext(stream)
    valid[0] = False
    assert await anext(stream) == "event: expired\ndata: {}\n\n"
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    stream = routes_module.status_events(state, lambda: True, interval=0)
    await anext(stream)
    await stream.aclose()


def test_routes_session_checks_lifecycle_and_bootstrap(monkeypatch, tmp_path, agent_service):
    state = MoonrakerObservation()
    integration = SimpleNamespace(state=state, start=Mock())
    container = SimpleNamespace(
        sessions=agent_service.sessions,
        chat_service=agent_service,
        moonraker_agent=integration,
        aclose=AsyncMock(),
    )
    monkeypatch.setattr(
        app_module,
        "get_settings",
        lambda: Settings(data_dir=tmp_path, printer_data_root=tmp_path, root_path="/klipperai"),
    )
    monkeypatch.setattr(app_module, "build_container", lambda settings: container)

    async def finite_stream(state_arg, valid):
        assert state_arg is state and valid()
        yield "event: status\ndata: {}\n\n"

    monkeypatch.setattr(routes_module, "status_events", finite_stream)
    with TestClient(app_module.create_app()) as client:
        integration.start.assert_called_once()
        session = client.post("/api/ui-sessions").json()["session_id"]
        params = {"session_id": session}
        assert "moonraker-events" in client.get("/api/bootstrap", params=params).json()["features"]
        base = "/klipperai/api/moonraker"
        assert client.get(base, params=params).json() == state.snapshot()
        response = client.get(base + "/events", params=params)
        assert response.text == "event: status\ndata: {}\n\n"
        assert response.headers["x-accel-buffering"] == "no"
        assert response.headers["cache-control"] == "no-store"
        for route in (base, base + "/events"):
            assert client.get(route, params={"session_id": "invalid"}).status_code == 403
        container.moonraker_agent = None
        assert client.get(base, params=params).status_code == 404
    container.aclose.assert_awaited_once()
