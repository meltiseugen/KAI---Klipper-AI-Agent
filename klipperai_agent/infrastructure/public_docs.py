"""Resolve and pin public HTTPS destinations, including every redirect hop."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

from klipperai_agent.domain.redaction import redact_text


async def resolve_addresses(host: str) -> list[str]:
    entries = await asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(entry[4][0]) for entry in entries))


def public_target(url: str, addresses: list[str]) -> tuple[httpx.URL, str]:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
        or len(url) > 2048
        or redact_text(url) != url
    ):
        raise ValueError("Only public HTTPS documentation is supported.")
    if not addresses or any(
        not ipaddress.ip_address(address).is_global or ipaddress.ip_address(address).is_multicast
        for address in addresses
    ):
        raise ValueError("Private, local and reserved documentation destinations are blocked.")
    # Connecting to the checked IP avoids a second DNS lookup and DNS rebinding.
    target = httpx.URL(url).copy_with(host=addresses[0], port=None, fragment=None)
    return target, parsed.hostname.encode("idna").decode("ascii")
