"""Cache one public source and its bounded indexes, independent of UI orchestration."""

import asyncio
from hashlib import sha256

from klipperai_agent.domain.investigation import utc_now
from klipperai_agent.domain.knowledge import (
    CachedDocument,
    ComponentIdentity,
    DocumentationFetcher,
    DocumentSource,
    KnowledgeRepository,
    KnowledgeResearcher,
    KnowledgeSetup,
)
from klipperai_agent.knowledge.buses import extract_bus_mappings
from klipperai_agent.knowledge.pdf_pages import pdf_pages
from klipperai_agent.knowledge.sources import grounded_mapping


async def cache_source(
    repository: KnowledgeRepository,
    fetcher: DocumentationFetcher,
    researcher: KnowledgeResearcher | None,
    source: DocumentSource,
    previous: dict[str, CachedDocument],
    component: ComponentIdentity | None = None,
    firmware: KnowledgeSetup | None = None,
) -> str:
    original, text, kind = await asyncio.wait_for(fetcher.fetch(source), timeout=30)
    doc = CachedDocument(
        id=source.id,
        title=source.title,
        url=source.url,
        kind=kind,
        component_key=source.component_key,
        digest=sha256(original).hexdigest(),
        fetched_at=utc_now(),
        content=text,
        pages=pdf_pages(text) if kind == "pdf" else [],
        bus_mappings=extract_bus_mappings(text),
        firmware_commit=firmware.firmware_commit if firmware else "",
        firmware_repository=firmware.firmware_repository if firmware else "",
        index_notes=[
            "PDF diagram labels and page locations are indexed. Image-only content requires visual review or a confirmed page note; no OCR or diagram-to-pin inference was performed."
        ]
        if kind == "pdf"
        else [],
    )
    doc.version = "Content SHA-256 " + doc.digest
    old = previous.get(doc.id)
    if old and old.digest == doc.digest:
        doc.fan_mappings = old.fan_mappings
    await asyncio.to_thread(repository.save_document, doc, original)
    if component and researcher and not doc.fan_mappings:
        mappings = await asyncio.wait_for(researcher.extract(component, doc), timeout=60)
        doc.fan_mappings = [item for item in mappings[:16] if grounded_mapping(item, doc)]
        await asyncio.to_thread(repository.save_document, doc, original)
    return "unchanged" if old and old.digest == doc.digest else "updated" if old else "added"
