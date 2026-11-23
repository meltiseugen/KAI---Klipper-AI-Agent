"""Cache one public source and its bounded indexes, independent of UI orchestration."""

import asyncio
from hashlib import sha256

from kai_agent.domain.investigation import utc_now
from kai_agent.domain.knowledge import (
    CachedDocument,
    ComponentIdentity,
    DocumentationFetcher,
    DocumentationResolver,
    DocumentSource,
    KnowledgeRepository,
    KnowledgeResearcher,
    KnowledgeSetup,
)
from kai_agent.domain.redaction import redact_text
from kai_agent.knowledge.buses import extract_bus_mappings
from kai_agent.knowledge.pdf_pages import pdf_pages
from kai_agent.knowledge.sources import document_source, grounded_mapping


async def component_sources(
    component: ComponentIdentity,
    setup: KnowledgeSetup,
    researcher: KnowledgeResearcher | None,
    resolver: DocumentationResolver | None = None,
) -> tuple[list[DocumentSource], bool]:
    """Discover references, retain legacy sources and honor explicit removals."""
    retained = []
    for url in component.reference_urls:
        try:
            source = document_source(component, url)
            if source.id not in setup.dismissed_documents:
                retained.append(source)
        except ValueError:
            continue
    if researcher is None:
        if not retained:
            raise ValueError(
                "Connect a model provider and enable web search for automatic research."
            )
        discovered, failed = [], False
    else:
        try:
            discovered = await asyncio.wait_for(researcher.discover(component, setup), timeout=90)
            failed = False
        except Exception:
            if not retained:
                raise
            discovered, failed = [], True
    sources = {}
    seen = set()
    for item in discovered + retained:
        source = document_source(component, item.url, item.title)
        if source.id in setup.dismissed_documents or source.id in seen:
            continue
        seen.add(source.id)
        try:
            expanded = (
                await asyncio.wait_for(resolver.resolve(source), timeout=90)
                if resolver
                else [source]
            )
            for reference in expanded:
                if reference.id not in setup.dismissed_documents:
                    sources[reference.id] = reference
        except Exception:
            failed = True
    return list(sources.values()), failed


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
        details_digest=sha256(redact_text(component.details).encode()).hexdigest()
        if component and component.details
        else "",
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
    if source.repository_commit:
        doc.version += " · Repository commit " + source.repository_commit
    old = previous.get(doc.id)
    unchanged = bool(old and old.digest == doc.digest and old.details_digest == doc.details_digest)
    if old and unchanged:
        doc.fan_mappings = old.fan_mappings
    await asyncio.to_thread(repository.save_document, doc, original)
    if component and researcher and not doc.fan_mappings:
        mappings = await asyncio.wait_for(researcher.extract(component, doc), timeout=60)
        doc.fan_mappings = [item for item in mappings[:16] if grounded_mapping(item, doc)]
        await asyncio.to_thread(repository.save_document, doc, original)
    return "unchanged" if unchanged else "updated" if old else "added"
