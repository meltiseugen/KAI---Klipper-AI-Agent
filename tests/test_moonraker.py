from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from klipperai_agent.infrastructure.moonraker import MoonrakerClient, MoonrakerError


def _client(handler) -> MoonrakerClient:
    client = MoonrakerClient("http://moonraker/", timeout_seconds=1)
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://moonraker"
    )
    return client


@pytest.mark.asyncio
async def test_moonraker_client_happy_paths_and_close() -> None:
    payloads = {
        "/server/info": {"result": {"klippy_connected": True}},
        "/printer/info": {"result": {"state": "ready"}},
        "/printer/objects/list": {"result": {"objects": ["toolhead", 3]}},
        "/printer/objects/query": {"result": {"status": {"toolhead": {"status": "Ready"}}}},
        "/machine/system_info": {"result": {"system_info": {"cpu_info": "pi"}}},
        "/machine/update/status": {"result": {"version_info": {}}},
        "/machine/peripherals/serial": {
            "result": {"serial_devices": [{"path": "/dev/tty"}, "bad"]}
        },
        "/machine/peripherals/usb": {"result": {"usb_devices": [{"product": "MCU"}, 4]}},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payloads[request.url.path])

    client = _client(handler)
    assert await client.ping() is True
    assert (await client.get_server_info())["klippy_connected"] is True
    assert (await client.get_printer_info())["state"] == "ready"
    assert await client.list_printer_objects() == ["toolhead", "3"]
    assert "toolhead" in await client.query_printer_objects({"toolhead": None})
    assert await client.get_system_info() == {"cpu_info": "pi"}
    assert await client.get_update_status() == {"version_info": {}}
    assert await client.list_serial_devices() == [{"path": "/dev/tty"}]
    assert await client.list_usb_devices() == [{"product": "MCU"}]
    await client.aclose()


@pytest.mark.asyncio
async def test_moonraker_client_alternate_valid_payloads() -> None:
    client = _client(lambda _request: httpx.Response(200, json={}))
    client._request = AsyncMock(
        side_effect=[
            ["a", 2],
            {"raw": "query"},
            {"raw": "system"},
        ]
    )
    assert await client.list_printer_objects() == ["a", "2"]
    assert await client.query_printer_objects({}) == {"raw": "query"}
    assert await client.get_system_info() == {"raw": "system"}
    await client.aclose()

    plain = _client(
        lambda _request: httpx.Response(200, json={"plain": "dictionary without result"})
    )
    assert await plain._request("GET", "/plain") == {"plain": "dictionary without result"}
    await plain.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method",
    [
        "get_server_info",
        "get_printer_info",
        "list_printer_objects",
        "query_printer_objects",
        "get_system_info",
        "get_update_status",
        "list_serial_devices",
        "list_usb_devices",
    ],
)
async def test_moonraker_client_rejects_unexpected_method_payloads(method: str) -> None:
    client = _client(lambda _request: httpx.Response(200, json={"result": "unexpected"}))
    call = getattr(client, method)
    with pytest.raises(MoonrakerError, match="unexpected"):
        await (call({}) if method == "query_printer_objects" else call())
    await client.aclose()


@pytest.mark.asyncio
async def test_moonraker_request_and_ping_wrap_http_failures() -> None:
    client = _client(lambda _request: httpx.Response(503, json={"error": "down"}))
    assert await client.ping() is False
    with pytest.raises(MoonrakerError, match="request failed"):
        await client.get_server_info()
    await client.aclose()

    scalar = _client(lambda _request: httpx.Response(200, json=["unexpected"]))
    with pytest.raises(MoonrakerError, match="unexpected payload for /scalar"):
        await scalar._request("GET", "/scalar")
    await scalar.aclose()
