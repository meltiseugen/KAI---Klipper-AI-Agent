import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from klipperai_agent.application import moonraker as methods_module
from klipperai_agent.domain.moonraker import (
    SUBSCRIPTIONS,
    MoonrakerObservation,
    RemoteMethodError,
    capabilities,
    gcode_filename,
    public_scalar,
)
from klipperai_agent.infrastructure.moonraker_agent import MoonrakerAgent, open_moonraker_socket
from klipperai_agent.infrastructure.moonraker_rpc import RpcError
from tests.moonraker_helpers import SocketPeer, methods, until


def test_observations_are_bounded_redacted_copied_and_marked_stale():
    state = MoonrakerObservation()
    state.connected = state.subscribed = True
    state.update({"extruder": {"temperature": 200, "target": 210, "pin": "PA1"}}, 100)
    state.update({"extruder": {"temperature": 202}, "configfile": {"secret": "private"}}, 101)
    state.update({"extruder": {"temperature": 1}}, 99)
    assert state.snapshot()["status"] == {"extruder": {"temperature": 202, "target": 210}}
    snapshot = state.snapshot()
    snapshot["status"]["extruder"]["target"] = 999
    assert state.status["extruder"]["target"] == 210 and not snapshot["stale"]
    state.disconnect()
    assert state.snapshot()["stale"] and state.observed_at
    state.update({"print_stats": {"filename": "test.gcode"}}, 1, initial=True)
    assert "extruder" not in state.status
    state.update({"heater_bed": {"target": 60}}, 0, initial=True)
    assert state.status == {"heater_bed": {"target": 60}}
    for status, timestamp in (([], 2), ({}, True), ({}, -1), ({}, float("nan")), ({}, 1e20)):
        with pytest.raises(ValueError):
            state.update(status, timestamp)
    assert public_scalar("api_key=sk-private-test-value") != "api_key=sk-private-test-value"
    assert len(public_scalar("a" * 1000)) == 512
    assert public_scalar(True) is True and public_scalar(None) is None
    for value in ({"nested": "data"}, [], 10**500, float("inf")):
        assert public_scalar(value) is None
    for filename in (
        "",
        "../printer.cfg",
        "/tmp/x",
        "C:/x",
        "a//b",
        "a/./b",
        "a\\b",
        "a\x00b",
        "a\x7fb",
        "x" * 513,
    ):
        with pytest.raises(ValueError):
            gcode_filename(filename)
    assert gcode_filename("folder/my #part.gcode") == "folder/my #part.gcode"


@pytest.mark.asyncio
async def test_session_bootstrap_is_ephemeral_bounded_and_rate_limited(monkeypatch):
    api = methods()
    now = [100.0]
    monkeypatch.setattr(methods_module.time, "monotonic", lambda: now[0])
    assert await api.dispatch("klipperai.status", None) == api.state.snapshot()
    for _ in range(10):
        session = await api.dispatch("klipperai.create_ui_session", {})
        assert api.sessions.exists(session["session_id"])
        assert session["session_id"] not in json.dumps(capabilities())
    with pytest.raises(RemoteMethodError, match="rate limit"):
        await api.dispatch("klipperai.create_ui_session", {})
    now[0] += 60
    assert (await api.dispatch("klipperai.create_ui_session", {}))["expires_at"]
    for params in ([1], "", {"url": "private"}):
        with pytest.raises(RemoteMethodError) as error:
            await api.dispatch("klipperai.capabilities", params)
        assert error.value.code == -32602


@pytest.mark.asyncio
async def test_registration_events_restart_resubscribe_and_reconnect():
    api = methods()
    status = {"klippy_state": "ready"}
    sockets = []

    def handler(request):
        method = request["method"]
        if method == "server.info":
            return {"result": status.copy()}
        if method == "printer.objects.list":
            return {"result": {"objects": [*SUBSCRIPTIONS, "gcode_move"]}}
        if method == "printer.objects.subscribe":
            assert request["params"] == {"objects": SUBSCRIPTIONS}
            # Update and bootstrap arrive while the initial subscribe call is in flight.
            sockets[-1].feed(
                {"method": "notify_status_update", "params": [{"extruder": {"temperature": 25}}, 2]}
            )
            sockets[-1].feed({"id": 100, "method": "klipperai.create_ui_session", "params": {}})
            return {
                "result": {"status": {"extruder": {"temperature": 20, "target": 0}}, "eventtime": 1}
            }
        return {"result": {"connection_id": 42}}

    async def connect(path):
        assert path == Path("moonraker.sock")
        remote = SocketPeer(handler)
        sockets.append(remote)
        return remote.reader, remote.writer

    agent = MoonrakerAgent(
        Path("moonraker.sock"), api, connector=connect, retry_seconds=0.001, heartbeat_seconds=0.01
    )
    agent.start()
    task = agent._task
    agent.start()
    assert agent._task is task
    try:
        await until(lambda: api.state.subscribed)
        remote = sockets[0]
        assert api.state.status["extruder"] == {"temperature": 25, "target": 0}
        assert api.state.registered and api.state.metadata_registered
        identify, database, event = remote.sent[:3]
        assert (
            identify["params"]["type"] == "agent"
            and identify["params"]["client_name"] == "klipperai"
        )
        assert database["params"] == {
            "namespace": "klipperai",
            "key": "integration",
            "value": capabilities(),
        }
        assert event["params"] == {"event": "klipperai_ready", "data": capabilities()}
        assert "session_id" not in json.dumps(database)
        remote.feed(
            {
                "method": "notify_status_update",
                "params": [{"print_stats": {"state": "printing"}}, 3],
            }
        )
        await until(lambda: "print_stats" in api.state.status)
        status["klippy_state"] = "shutdown"
        remote.feed({"method": "notify_klippy_shutdown"})
        await until(lambda: api.state.klippy_state == "shutdown")
        assert api.state.snapshot()["stale"]
        status["klippy_state"] = "ready"
        remote.feed({"method": "notify_klippy_ready"})
        await until(lambda: api.state.subscribed)
        assert "print_stats" not in api.state.status
        remote.reader.feed_eof()
        await until(lambda: len(sockets) == 2 and api.state.subscribed)
        assert remote.closed and sockets[1].sent[0]["method"] == "server.connection.identify"
        assert all(
            request.get("method")
            in {
                None,
                "server.connection.identify",
                "server.database.post_item",
                "connection.send_event",
                "server.info",
                "printer.objects.list",
                "printer.objects.subscribe",
            }
            for socket in sockets
            for request in socket.sent
        )
    finally:
        await agent.aclose()
    assert sockets[-1].closed and api.state.snapshot()["stale"] and task.done()
    await agent.aclose()


@pytest.mark.asyncio
async def test_unavailable_connector_retries_and_can_be_stopped():
    connector = AsyncMock(side_effect=OSError("private socket path"))
    agent = MoonrakerAgent(Path("socket"), methods(), connector=connector, retry_seconds=0.001)
    agent.start()
    await until(lambda: connector.await_count >= 2)
    assert "private" not in agent.state.error
    await agent.aclose()


@pytest.mark.asyncio
async def test_unix_connector_supported_and_unsupported(monkeypatch):
    connect = AsyncMock(return_value=("reader", "writer"))
    monkeypatch.setattr(asyncio, "open_unix_connection", connect, raising=False)
    assert await open_moonraker_socket(Path("local.sock")) == ("reader", "writer")
    connect.assert_awaited_once_with("local.sock", limit=131072)
    monkeypatch.delattr(asyncio, "open_unix_connection")
    with pytest.raises(NotImplementedError):
        await open_moonraker_socket(Path("local.sock"))


@pytest.mark.asyncio
async def test_database_failure_does_not_disable_observation():
    def handler(request):
        if request["method"] == "server.database.post_item":
            return {"error": {"message": "private details"}}
        if request["method"] == "server.info":
            return {"result": {"klippy_state": "startup"}}
        return {"result": {}}

    remote = SocketPeer(handler)
    agent = MoonrakerAgent(Path("socket"), methods(), connector=remote.connect)
    agent.start()
    await until(lambda: agent.state.klippy_state == "startup")
    assert agent.state.connected and not agent.state.metadata_registered
    assert agent.state.error == "Moonraker metadata namespace is unavailable."
    await agent.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "responses,error",
    [
        ([[]], "Invalid Moonraker server info"),
        ([{"klippy_state": "ready"}, []], None),
        ([{"klippy_state": "ready"}, {"objects": []}, []], None),
        ([{"klippy_state": "ready"}, {"objects": []}, {"status": {}, "eventtime": 0}], None),
        ([{"klippy_state": "other"}], None),
    ],
)
async def test_unexpected_info_or_subscriptions_are_not_reported_live(responses, error):
    agent = MoonrakerAgent(Path("socket"), methods())
    peer = SimpleNamespace(call=AsyncMock(side_effect=responses))
    if error:
        with pytest.raises(RpcError, match=error):
            await agent._refresh(peer)
    else:
        await agent._refresh(peer)
    assert not agent.state.subscribed


@pytest.mark.asyncio
@pytest.mark.parametrize("during", ["server.info", "printer.objects.subscribe"])
async def test_restart_during_snapshot_never_marks_old_data_live(during):
    agent = MoonrakerAgent(Path("socket"), methods())

    async def reply(method, params=None):
        if method == during:
            agent._notify("notify_klippy_disconnected", None)
        return {
            "klippy_state": "ready",
            "objects": ["extruder"],
            "status": {"extruder": {"temperature": 200}},
            "eventtime": 1,
        }

    await agent._refresh(SimpleNamespace(call=reply))
    assert not agent.state.subscribed and agent.state.status == {}


def test_subscription_update_validation_and_bounded_buffer():
    agent = MoonrakerAgent(Path("socket"), methods())
    agent._notify("unknown", {})
    agent._notify("notify_status_update", "ignored while disconnected")
    agent._subscribing = True
    with pytest.raises(ValueError, match="Invalid status"):
        agent._notify("notify_status_update", [])
    for _ in range(32):
        agent._notify("notify_status_update", [{}, 1])
    with pytest.raises(ValueError, match="overflow"):
        agent._notify("notify_status_update", [{}, 1])
