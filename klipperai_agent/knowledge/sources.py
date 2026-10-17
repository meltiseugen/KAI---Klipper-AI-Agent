"""Identity-scoped evidence. No embedded board or manufacturer catalog."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from urllib.parse import urlsplit, urlunsplit

from klipperai_agent.domain.knowledge import (
    CachedDocument,
    ComponentIdentity,
    DocumentSource,
    FanMapping,
)
from klipperai_agent.domain.redaction import redact_text


def component_key(component: ComponentIdentity) -> str:
    identity = [
        component.role,
        component.category,
        component.manufacturer.strip().casefold(),
        component.model.strip().casefold(),
        component.revision.strip().casefold(),
    ]
    return sha256(json.dumps(identity).encode()).hexdigest()


def document_source(component: ComponentIdentity, url: str, title: str = "") -> DocumentSource:
    parsed = urlsplit(url.strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
        or len(url) > 2048
        or redact_text(url) != url
    ):
        raise ValueError(
            "Documentation must use a public HTTPS URL without credentials or a custom port."
        )
    url = urlunsplit(("https", parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))
    # Search commonly cites GitHub's file viewer. Fetch the actual document rather
    # than indexing navigation HTML or mistaking a PDF viewer for a manual.
    parts = parsed.path.split("/")
    if parsed.hostname == "github.com" and len(parts) >= 6 and parts[3] == "blob":
        url = "https://raw.githubusercontent.com/" + "/".join([*parts[1:3], *parts[4:]])
    key = component_key(component)
    return DocumentSource(
        sha256((key + url).encode()).hexdigest()[:32], title[:160] or parsed.hostname, url, key
    )


def component_documents(
    component: ComponentIdentity, documents: list[CachedDocument]
) -> list[CachedDocument]:
    return [doc for doc in documents if doc.component_key == component_key(component)]


def grounded_mapping(mapping: FanMapping, document: CachedDocument) -> bool:
    # A quote proves where a candidate came from, not that a search hit is the right board.
    quote = " ".join(mapping.quote.split())
    return bool(
        quote
        and quote in " ".join(document.content.split())
        and re.search(r"(?<![A-Za-z0-9_])" + re.escape(mapping.pin) + r"(?![A-Za-z0-9_])", quote)
        and mapping.connector.casefold() in quote.casefold()
    )


def mapping_evidence(component: ComponentIdentity, documents: list[CachedDocument]) -> dict:
    candidates: list[dict] = []
    for doc in component_documents(component, documents):
        for mapping in doc.fan_mappings:
            if grounded_mapping(mapping, doc):
                candidates.append(
                    {
                        **mapping.model_dump(),
                        "source_id": doc.id,
                        "url": doc.url,
                        "digest": doc.digest,
                        "fetched_at": doc.fetched_at,
                    }
                )
    candidates.sort(key=lambda item: (item["connector"], item["pin"], item["source_id"]))
    by_connector: dict[str, set[str]] = {}
    for item in candidates:
        by_connector.setdefault(item["connector"].casefold(), set()).add(item["pin"])
    conflicts = sorted(name for name, pins in by_connector.items() if len(pins) > 1)
    signature = (
        sha256(
            json.dumps(
                {
                    "mcu": component.mcu,
                    "connection": component.connection,
                    "confirmed": component.confirmed,
                    "candidates": [
                        {key: value for key, value in item.items() if key != "fetched_at"}
                        for item in candidates
                    ],
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        if candidates
        else ""
    )
    return {"candidates": candidates, "conflicts": conflicts, "signature": signature}
