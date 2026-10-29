"""Bounded extraction of page text, diagram labels and visual-review locators."""

import io
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

import klipperai_agent.infrastructure.pdf_index as pdf
from klipperai_agent.agent.tools.knowledge import SearchKnowledgeArguments, SearchKnowledgeTool
from klipperai_agent.application.knowledge_refresh import cache_source
from klipperai_agent.domain.knowledge import CachedDocument
from klipperai_agent.knowledge.firmware import firmware_key
from klipperai_agent.knowledge.pdf_pages import pdf_pages
from klipperai_agent.knowledge.retrieval import search_documents
from tests.test_agent import tool_context as tool_context
from tests.test_firmware_knowledge import note, pdf_document, pinned
from tests.test_knowledge_storage import repository


def pdf_bytes():
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    form = DecodedStreamObject()
    form.set_data(b"0 0 m 10 10 l S")
    form.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Form"),
            NameObject("/BBox"): ArrayObject(
                [NumberObject(0), NumberObject(0), NumberObject(10), NumberObject(10)]
            ),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
            NameObject("/XObject"): DictionaryObject({NameObject("/D"): form}),
        }
    )
    content = DecodedStreamObject()
    content.set_data(
        b"BT /F1 12 Tf 10 100 Td (Figure 1: FAN0 PA8 connector pinout) Tj ET\n0 0 m 10 10 l S\n/D Do"
    )
    page[NameObject("/Contents")] = content
    writer.add_blank_page(width=200, height=200)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_actual_pdf_text_and_diagram_locators_are_page_scoped():
    raw = pdf_bytes()
    text = pdf.parse_pdf(raw)
    assert pdf.index_pdf(raw) == text  # Exercise the bounded, installed-module child process.
    pages = pdf_pages(text)
    assert len(pages) == 2 and pages[0].images == 1 and pages[0].vector_paths >= 2
    assert "FAN0 PA8" in pages[0].text and pages[0].diagram_labels
    assert "No readable text" in pages[1].text and pages[1].needs_visual_review
    doc = CachedDocument(
        id="d" * 32,
        title="Manual",
        url="https://example.org/manual.pdf",
        kind="pdf",
        digest="a" * 64,
        fetched_at="now",
        content=text,
        pages=pages,
    )
    passages = search_documents([doc], "FAN0 connector", {doc.id})
    assert passages[0]["page"] == 1 and passages[0]["url"].endswith("#page=1")
    assert "[PDF page 2;" not in passages[0]["excerpt"]
    assert not pdf_pages("no page metadata")


@pytest.mark.parametrize(
    "status,output",
    [
        (1, b""),
        (0, b"x" * 1000001),
        (0, b"{}"),
        (0, b'{"text":42}'),
        (0, b'{"text":"' + b"x" * 300001 + b'"}'),
    ],
    ids=["failed", "oversized-output", "missing-field", "non-text", "oversized-text"],
)
def test_index_worker_rejects_invalid_or_oversized_results(monkeypatch, status, output):
    monkeypatch.setattr(
        pdf.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=status, stdout=output),
    )
    with pytest.raises(ValueError, match="indexing failed"):
        pdf.index_pdf(b"%PDF-1.7")


def test_worker_input_timeout_and_parser_budgets(monkeypatch):
    with pytest.raises(ValueError, match="download"):
        pdf.index_pdf(b"x" * (8 * 1024 * 1024 + 1))

    def timeout(*args, **kwargs):
        raise pdf.subprocess.TimeoutExpired("parser", 12)

    monkeypatch.setattr(pdf.subprocess, "run", timeout)
    with pytest.raises(ValueError, match="indexing failed"):
        pdf.index_pdf(b"%PDF-1.7")
    import pypdf

    for reader, message in [
        (SimpleNamespace(is_encrypted=True), "Encrypted"),
        (SimpleNamespace(is_encrypted=False, pages=[None] * 81), "oversized"),
    ]:
        monkeypatch.setattr(pypdf, "PdfReader", lambda *args, **kwargs: reader)
        with pytest.raises(ValueError, match=message):
            pdf.parse_pdf(b"fixture")
    page = SimpleNamespace(get_contents=lambda: SimpleNamespace(get_data=lambda: b"x" * 2000001))
    monkeypatch.setattr(
        pypdf,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(is_encrypted=False, pages=[page]),
    )
    with pytest.raises(ValueError, match="content"):
        pdf.parse_pdf(b"fixture")
    page.get_contents = lambda: None
    page.extract_text = lambda **kwargs: "x" * 24001
    with pytest.raises(ValueError, match="page text"):
        pdf.parse_pdf(b"fixture")
    page.extract_text = lambda **kwargs: "x" * 23900
    monkeypatch.setattr(
        pypdf,
        "PdfReader",
        lambda *args, **kwargs: SimpleNamespace(is_encrypted=False, pages=[page] * 13),
    )
    with pytest.raises(ValueError, match="PDF text"):
        pdf.parse_pdf(b"fixture")


def test_worker_main_linux_cap_and_bounded_stdin(monkeypatch):
    resource = SimpleNamespace(RLIMIT_AS=9, setrlimit=lambda *args: None)
    monkeypatch.setitem(sys.modules, "resource", resource)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(pdf_bytes())))
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    pdf.main()
    assert "FAN0" in json.loads(output.getvalue())["text"]
    monkeypatch.setattr(
        sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"x" * (8 * 1024 * 1024 + 1)))
    )
    with pytest.raises(ValueError, match="download"):
        pdf.main()


@pytest.mark.asyncio
async def test_pdf_cache_keeps_pages_and_searchable_user_diagram_notes(tmp_path, tool_context):
    from klipperai_agent.knowledge.sources import document_source

    data = pinned()
    component = data.components[0]
    source = document_source(component, "https://example.org/manual.pdf")
    raw = pdf_bytes()
    text = pdf.parse_pdf(raw)
    store = repository(tmp_path)
    await cache_source(
        store,
        SimpleNamespace(fetch=AsyncMock(return_value=(raw, text, "pdf"))),
        None,
        source,
        {},
        component,
    )
    doc = store.documents()[0]
    assert doc.pages and doc.index_notes and store.original(doc.id) == raw
    doc.id = "d" * 32
    doc.digest = "a" * 64
    data.diagram_notes = [note(text="Power connector diagram confirmed at top right")]
    knowledge = SimpleNamespace(read=AsyncMock(return_value=(data, [doc], False)))
    result = await SearchKnowledgeTool(knowledge).execute(
        SearchKnowledgeArguments(query="Power connector", role="mainboard"), tool_context
    )
    assert any(item.get("origin") == "user_confirmed_note" for item in result["passages"])
    assert any(
        citation.page_number == 1 and citation.source_digest == doc.digest
        for citation in tool_context.citations
    )
    doc.digest = "b" * 64
    assert not any(
        item.get("origin") == "user_confirmed_note"
        for item in (
            await SearchKnowledgeTool(knowledge).execute(
                SearchKnowledgeArguments(query="Power connector"), tool_context
            )
        )["passages"]
    )
    firmware = pdf_document()
    firmware.component_key = firmware_key(data)
    firmware.content = "firmware shaper reference"
    firmware.firmware_commit = data.firmware_commit
    knowledge.read.return_value = (data, [firmware], False)
    result = await SearchKnowledgeTool(knowledge).execute(
        SearchKnowledgeArguments(query="firmware shaper", role="firmware"), tool_context
    )
    assert result["passages"][0]["firmware_commit"] == data.firmware_commit


@pytest.mark.asyncio
async def test_public_fetcher_indexes_the_pdf_before_caching(monkeypatch):
    import httpx

    import klipperai_agent.infrastructure.documentation as module
    from klipperai_agent.domain.knowledge import ComponentIdentity
    from klipperai_agent.knowledge.sources import document_source

    client_type = httpx.AsyncClient
    raw = pdf_bytes()
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, content=raw, headers={"content-type": "application/pdf"}
                )
            ),
            **kwargs,
        ),
    )
    source = document_source(ComponentIdentity(role="mainboard"), "https://example.org/manual.pdf")
    original, text, kind = await module.PublicDocumentationFetcher(
        AsyncMock(return_value=["1.1.1.1"])
    ).fetch(source)
    assert original == raw and kind == "pdf" and "FAN0 PA8" in text and pdf_pages(text)
