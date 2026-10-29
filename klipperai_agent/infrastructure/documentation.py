"""Bounded public-document downloads. No cookies, credentials or private networks."""

from __future__ import annotations

import asyncio
from html.parser import HTMLParser
from typing import Awaitable, Callable
from urllib.parse import urljoin, urlsplit

import httpx

from klipperai_agent.domain.knowledge import DocumentSource
from klipperai_agent.infrastructure.pdf_index import index_pdf
from klipperai_agent.infrastructure.public_docs import public_target, resolve_addresses


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"p", "div", "br", "tr", "h1", "h2", "h3", "li", "pre"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data + " ")


def extract_document(original: bytes, content_type: str) -> tuple[str, str]:
    for signature, kind in (
        (b"%PDF-", "pdf"),
        (b"\x89PNG\r\n\x1a\n", "image"),
        (b"\xff\xd8\xff", "jpeg"),
    ):
        if original.startswith(signature):
            return "", kind
    if "pdf" in content_type or content_type.startswith("image/") or b"\x00" in original:
        raise ValueError("Unsupported or invalid binary documentation.")
    if len(original) > 512000:
        raise ValueError("Text documentation exceeds download size limit.")
    text = original.decode("utf-8", errors="replace")
    kind = "text"
    if "html" in content_type or "<html" in text[:1000].casefold():
        parser = _Text()
        parser.feed(text)
        text = "\n".join(
            line.strip() for line in "".join(parser.parts).splitlines() if line.strip()
        )
        kind = "html"
    if not text.strip() or len(text) > 300000:
        raise ValueError("Documentation text is empty or exceeds indexing limit.")
    return text, kind


class PublicDocumentationFetcher:
    def __init__(self, resolver: Callable[[str], Awaitable[list[str]]] = resolve_addresses):
        self._resolver = resolver

    async def fetch(self, source: DocumentSource) -> tuple[bytes, str, str]:
        url = source.url
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
            for _ in range(4):
                # Syntax is checked before DNS; target validation also checks all resolved IPs.
                parsed = urlsplit(url)
                public_target(url, ["1.1.1.1"])
                target, host = public_target(url, await self._resolver(str(parsed.hostname)))
                client.cookies.clear()
                async with client.stream(
                    "GET",
                    target,
                    headers={"Host": host, "Accept-Encoding": "identity"},
                    extensions={"sni_hostname": host},
                ) as response:
                    if response.is_redirect:
                        url = urljoin(url, response.headers.get("location", ""))
                        continue
                    response.raise_for_status()
                    if response.headers.get("content-encoding", "identity") != "identity":
                        raise ValueError("Compressed documentation is not accepted.")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 8 * 1024 * 1024:
                            raise ValueError("Documentation exceeds download size limit.")
                    original = bytes(data)
                    text, kind = extract_document(
                        original, response.headers.get("content-type", "")
                    )
                    if kind == "pdf":
                        text = await asyncio.to_thread(index_pdf, original)
                    return original, text, kind
        raise ValueError("Too many documentation redirects.")
