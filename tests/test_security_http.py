import pytest
from fastapi.testclient import TestClient

import klipperai_agent.web.app as app_module
from klipperai_agent.runtime.settings import Settings
from klipperai_agent.web.security import RequestSecurity, same_origin
from tests.test_app import _FakeContainer


def test_http_origin_checks_headers_and_private_validation_errors(monkeypatch, tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        security_allowed_hosts="testserver, printer.local",
        security_allowed_origins="https://printer.example, ",
    )
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(app_module, "build_container", lambda _: _FakeContainer())
    with TestClient(app_module.create_app()) as client:
        for path in ("/", "/embed", "/api/bootstrap?session_id=session-1"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["referrer-policy"] == "no-referrer"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert "frame-ancestors 'self'" in response.headers["content-security-policy"]
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404
        assert client.get("/", headers={"Host": "attacker.invalid"}).status_code == 400
        for headers in (
            {"Origin": "https://attacker.invalid"},
            {"Sec-Fetch-Site": "cross-site"},
            {"Origin": "http://["},
            {"Origin": "null"},
        ):
            response = client.post("/api/ui-sessions", headers=headers)
            assert response.status_code == 403
            assert response.headers["cache-control"] == "no-store"
        for headers in (
            {"Origin": "http://testserver"},
            {"Origin": "https://printer.example"},
            {"Origin": "https://remote-proxy.example", "Sec-Fetch-Site": "same-origin"},
        ):
            assert client.post("/api/ui-sessions", headers=headers).status_code == 200
        assert (
            client.post(
                "/api/ui-sessions", headers={"Content-Type": "text/plain"}, content="{}"
            ).status_code
            == 415
        )
        assert (
            client.post(
                "/api/ui-sessions",
                headers={"Content-Type": "application/json; charset=utf-8"},
                content="{}",
            ).status_code
            == 200
        )
        invalid = client.post(
            "/api/chat", json={"session_id": "valid", "message": {"api_key": "private-value"}}
        )
        assert invalid.status_code == 422 and "private-value" not in invalid.text
        # The attachment UI and both chat endpoints share bounded text-artifact limits.
        payload = {
            "session_id": "valid",
            "message": "hello",
            "artifacts": [
                {"kind": "config_snippet", "label": str(index), "content": "x" * 39000}
                for index in range(30)
            ],
        }
        assert client.post("/api/chat", json=payload).status_code == 422
        payload["artifacts"] = payload["artifacts"][:4]
        assert client.post("/api/chat", json=payload).status_code == 200


@pytest.mark.asyncio
async def test_security_middleware_preserves_streaming_and_non_http_events():
    sent = []
    received = []
    chunks = iter(
        [
            {"type": "http.request", "body": b"a", "more_body": True},
            {"type": "http.request", "body": b"b", "more_body": False},
            {"type": "http.disconnect"},
        ]
    )

    async def receive():
        return next(chunks)

    async def send(message):
        sent.append(message)

    async def app(scope, receive, send):
        if scope["type"] == "lifespan":
            sent.append({"type": "lifespan.startup.complete"})
            return
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"cache-control", b"public"), (b"content-type", b"text/event-stream")],
            }
        )
        received.append(await receive())
        await send({"type": "http.response.body", "body": b"data: progress\n\n", "more_body": True})
        received.append(await receive())
        received.append(await receive())
        await send({"type": "http.response.body", "body": b"data: result\n\n", "more_body": False})

    middleware = RequestSecurity(app)
    await middleware({"type": "lifespan"}, receive, send)
    await middleware({"type": "http", "path": "/api/chat/stream", "headers": []}, receive, send)
    assert sent[0]["type"] == "lifespan.startup.complete"
    assert dict(sent[1]["headers"])[b"cache-control"] == b"no-store"
    assert sent[2]["more_body"] is True and sent[3]["more_body"] is False
    assert [item.get("body") for item in received] == [b"a", b"b", None]
    assert same_origin("https://printer:8443", "printer:8443", "https")
    for origin in (
        "https://printer:8443/path",
        "https://printer:8443?q=1",
        "https://printer:8443#x",
        "http://printer:8443",
        "http://[",
    ):
        assert not same_origin(origin, "printer:8443", "https")
