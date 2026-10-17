"""Browser origin checks and response headers without buffering requests or SSE."""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SECURITY_HEADERS = {
    b"x-content-type-options": b"nosniff",
    b"referrer-policy": b"no-referrer",
    b"x-frame-options": b"SAMEORIGIN",
    b"content-security-policy": b"object-src 'none'; base-uri 'none'; frame-ancestors 'self'",
    b"permissions-policy": b"camera=(), microphone=(), geolocation=(), usb=(), serial=()",
    b"cache-control": b"no-store",
}


def same_origin(origin: str, host: str, scheme: str) -> bool:
    try:
        parsed = urlsplit(origin)
        return (
            parsed.scheme == scheme
            and parsed.netloc == host
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


class RequestSecurity:
    def __init__(self, app: ASGIApp, allowed_origins: str = ""):
        self.app = app
        self.allowed_origins = {
            item.strip().rstrip("/") for item in allowed_origins.split(",") if item.strip()
        }

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def secure_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() not in SECURITY_HEADERS
                ]
                message["headers"] = headers + list(SECURITY_HEADERS.items())
            await send(message)

        async def reject(code: int, detail: str) -> None:
            await JSONResponse({"detail": detail}, code)(scope, receive, secure_send)

        headers = {key.lower(): value.decode("latin1") for key, value in scope["headers"]}
        if "/api/" not in scope["path"]:
            await self.app(scope, receive, secure_send)
            return
        origin = headers.get(b"origin")
        site = headers.get(b"sec-fetch-site", "")
        # Same-origin Fetch Metadata survives trusted proxies that rewrite Host.
        if site == "cross-site" or (
            origin
            and site != "same-origin"
            and origin not in self.allowed_origins
            and not same_origin(origin, headers.get(b"host", ""), scope.get("scheme", "http"))
        ):
            await reject(403, "Cross-origin API access is not allowed.")
            return
        content_type = headers.get(b"content-type", "")
        if content_type and content_type.split(";", 1)[0].strip().lower() != "application/json":
            await reject(415, "API request bodies must use application/json.")
            return
        await self.app(scope, receive, secure_send)
