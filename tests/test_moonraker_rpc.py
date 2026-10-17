import asyncio
from unittest.mock import AsyncMock

import pytest

from klipperai_agent.infrastructure.moonraker_rpc import MoonrakerRpc, RpcError
from tests.moonraker_helpers import SocketPeer, methods, until


@pytest.mark.asyncio
async def test_rpc_correlates_responses_and_serves_bounded_methods():
    remote = SocketPeer()
    api = methods()
    notices = []
    peer = MoonrakerRpc(
        remote.reader, remote.writer, api.dispatch, lambda *args: notices.append(args)
    )
    first = asyncio.create_task(peer.call("server.info"))
    second = asyncio.create_task(peer.call("printer.objects.list"))
    await until(lambda: len(remote.sent) == 2)
    remote.feed({"id": remote.sent[1]["id"], "result": {"objects": []}})
    remote.feed({"id": remote.sent[0]["id"], "result": {"klippy_state": "ready"}})
    assert await first == {"klippy_state": "ready"}
    assert await second == {"objects": []}
    remote.feed({"method": "notify_klippy_ready", "params": []})
    for identifier, method, params in (
        (1, "klipperai.capabilities", {}),
        ("external", "klipperai.create_ui_session", {}),
        (2, "printer.gcode.script", {"script": "G28"}),
        (3, "klipperai.status", {"filename": "private"}),
    ):
        remote.feed({"id": identifier, "method": method, "params": params})
    await until(lambda: len(remote.sent) == 6)
    assert notices == [("notify_klippy_ready", [])]
    assert remote.sent[2]["result"]["printer_access"] == "read_only"
    session = remote.sent[3]["result"]
    assert api.sessions.exists(session["session_id"])
    assert session["embed_path"].startswith("/klipperai/embed?session=")
    assert remote.sent[4]["error"]["code"] == -32601
    assert remote.sent[5]["error"]["code"] == -32602
    # Bad IDs and uncorrelated responses cannot create a new request or session.
    remote.feed({"id": True, "method": "klipperai.create_ui_session"})
    remote.feed({"id": "unknown", "result": {}})
    peer.dispatch = AsyncMock(side_effect=RuntimeError("private exception"))
    remote.feed({"id": 4, "method": "klipperai.status"})
    await until(lambda: len(remote.sent) == 7)
    assert remote.sent[-1]["error"] == {"code": -32603, "message": "KlipperAI method failed."}
    await peer.aclose()
    assert remote.closed and not peer._pending
    with pytest.raises(RpcError, match="closed"):
        await peer.call("server.info")


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [{"error": {"message": "secret"}}, {}])
async def test_rpc_rejected_or_missing_result_is_sanitized(response):
    remote = SocketPeer(lambda request: response)
    peer = MoonrakerRpc(remote.reader, remote.writer, methods().dispatch, lambda *args: None)
    with pytest.raises(RpcError, match="rejected") as error:
        await peer.call("server.info")
    assert "secret" not in str(error.value)
    await peer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "frame",
    [b"[]\x03", b'{"jsonrpc":"1.0"}\x03', b"bad\x03", b"x" * 131073],
    ids=["non-object", "version", "invalid-json", "oversized"],
)
async def test_rpc_invalid_frames_fail_pending_calls_and_close(frame):
    remote = SocketPeer()
    peer = MoonrakerRpc(remote.reader, remote.writer, methods().dispatch, lambda *args: None)
    pending = asyncio.create_task(peer.call("server.info"))
    await until(lambda: bool(remote.sent))
    remote.reader.feed_data(frame)
    with pytest.raises(RpcError):
        await pending
    with pytest.raises(RpcError):
        await peer.task
    await peer.aclose()
    assert remote.closed


@pytest.mark.asyncio
async def test_rpc_timeout_eof_and_failed_write_release_pending_calls():
    remote = SocketPeer()
    peer = MoonrakerRpc(
        remote.reader, remote.writer, methods().dispatch, lambda *args: None, timeout=0.01
    )
    with pytest.raises(asyncio.TimeoutError):
        await peer.call("server.info")
    assert not peer._pending
    remote.writer.drain = AsyncMock(side_effect=OSError("write failed"))
    with pytest.raises(OSError):
        await peer.call("server.info")
    assert not peer._pending
    remote.writer.drain = AsyncMock()
    pending = asyncio.create_task(peer.call("server.info"))
    await until(lambda: len(remote.sent) == 3)
    remote.reader.feed_eof()
    with pytest.raises(RpcError):
        await pending
    remote.writer.wait_closed = AsyncMock(side_effect=OSError())
    await peer.aclose()


@pytest.mark.asyncio
async def test_rpc_cancelled_caller_and_notification_failure():
    remote = SocketPeer()

    def reject(*args):
        raise ValueError("private notification")

    peer = MoonrakerRpc(remote.reader, remote.writer, methods().dispatch, reject)
    pending = asyncio.create_task(peer.call("server.info"))
    await until(lambda: bool(remote.sent))
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    remote.feed({"method": "notify_status_update", "params": "bad"})
    with pytest.raises(RpcError, match="invalid frame"):
        await peer.task
    await peer.aclose()
