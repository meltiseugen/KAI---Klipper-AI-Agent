"""Immutable firmware references, diagram notes and user-only observation writes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from klipperai_agent.application.knowledge import PrinterKnowledge
from klipperai_agent.application.knowledge_observations import record_diagram
from klipperai_agent.domain.hardware import DiagramNote, PdfPageIndex
from klipperai_agent.domain.knowledge import KnowledgeConflict, KnowledgeSetup
from klipperai_agent.knowledge.buses import bus_evidence
from klipperai_agent.knowledge.firmware import firmware_key, firmware_scope, firmware_sources
from tests.knowledge_helpers import documents, setup
from tests.test_hardware_knowledge import bus_documents, observation
from tests.test_knowledge_storage import repository


def pinned():
    return setup().copy(
        update={
            "firmware_repository": "https://github.com/Klipper3d/klipper",
            "firmware_commit": "a" * 40,
        }
    )


@pytest.mark.parametrize(
    "repo,commit",
    [
        ("http://localhost/repo", "a" * 40),
        ("https://github.com/x/y", "main"),
        ("", "a" * 40),
        ("https://github.com/x/y", ""),
    ],
)
def test_rejects_mutable_or_ambiguous_firmware_references(repo, commit):
    with pytest.raises(ValidationError):
        KnowledgeSetup(firmware_repository=repo, firmware_commit=commit)


def test_exact_commit_sources_and_live_prefix_do_not_claim_compatibility():
    data = pinned()
    sources = firmware_sources(data)
    assert len(sources) == 3 and all("/" + "a" * 40 + "/docs/" in source.url for source in sources)
    assert all(source.component_key == firmware_key(data) for source in sources)
    assert not firmware_sources(setup())
    matched = firmware_scope(data, "v0.13.0-10-gaaaaaaa")
    assert matched["commit_prefix_matches"] and not matched["compatibility_verified"]
    assert not firmware_scope(data, "v0.13.0")["commit_prefix_matches"]
    assert (
        KnowledgeSetup(
            firmware_repository=data.firmware_repository, firmware_commit="B" * 40
        ).firmware_commit
        == "b" * 40
    )


@pytest.mark.asyncio
async def test_commit_cache_is_immutable_scoped_and_has_no_branch_fallback(tmp_path):
    fetch = AsyncMock(return_value=(b"readable", "probe firmware settings", "text"))
    service = PrinterKnowledge(repository(tmp_path), SimpleNamespace(fetch=fetch), {})
    data = pinned()
    data.components = []
    saved = await service.save(data)
    await service.start_refresh()
    await service._task
    assert service.job["state"] == "completed"
    docs = (await service.read())[1]
    assert len(docs) == 3 and all(doc.firmware_commit == "a" * 40 for doc in docs)
    assert len((await service.status())["documents"]) == 3
    changed = saved.copy(update={"firmware_commit": "b" * 40})
    await service.save(changed)
    assert (await service.read())[1] == []
    fetch.side_effect = ValueError("not found")
    await service.start_refresh()
    await service._task
    assert service.job["state"] == "partial"
    assert all("fallback" in message for message in service.job["changes"])
    assert all("/" + "b" * 40 + "/" in call.args[0].url for call in fetch.await_args_list[-3:])


def pdf_document():
    doc = documents()[0]
    doc.id = "d" * 32
    doc.pages = [PdfPageIndex(page=1, start_line=1, end_line=3, text="diagram")]
    return doc


def note(**updates):
    values = dict(
        document_id="d" * 32,
        digest="a" * 64,
        page=1,
        text="Connector label at the upper right",
        confirmed=True,
    )
    values.update(updates)
    return DiagramNote(**values)


def test_diagram_notes_are_confirmed_page_scoped_and_stale_when_source_changes():
    data = record_diagram(setup(), note(), [pdf_document()])
    assert data.diagram_notes[0].observed_at
    assert (
        len(
            record_diagram(
                data, note(text="Replacement description"), [pdf_document()]
            ).diagram_notes
        )
        == 1
    )
    for invalid in (note(confirmed=False), note(page=2), note(digest="b" * 64)):
        with pytest.raises(KnowledgeConflict):
            record_diagram(data, invalid, [pdf_document()])
    data.diagram_notes = [note(document_id=f"{number:032x}") for number in range(64)]
    with pytest.raises(KnowledgeConflict, match="limit"):
        record_diagram(data, note(), [pdf_document()])


@pytest.mark.asyncio
async def test_server_owned_reviews_inventory_and_notes_cannot_be_forged_by_details_save(tmp_path):
    store = repository(tmp_path)
    service = PrinterKnowledge(store, SimpleNamespace(fetch=AsyncMock()), {})
    data = await service.save(setup())
    docs = bus_documents()
    store.save_document(docs[0], b"source")
    evidence = bus_evidence(data.components[0], docs)
    with pytest.raises(KnowledgeConflict):
        await service.review_buses("missing", evidence["signature"], data.revision)
    with pytest.raises(KnowledgeConflict):
        await service.review_buses("mainboard", "wrong", data.revision)
    data = await service.review_buses("mainboard", evidence["signature"], data.revision)
    assert data.reviewed_bus_mappings
    data = await service.observe(observation(), data.revision)
    with pytest.raises(KnowledgeConflict):
        await service.observe(observation(), 0)
    doc = pdf_document()
    store.save_document(doc, b"pdf source")
    data = await service.observe(note(), data.revision)
    assert data.diagram_notes
    malicious = data.copy(
        update={
            "connectors": [],
            "diagram_notes": [],
            "reviewed_bus_mappings": {"mainboard": "invented"},
            "validation": {"physical_wiring_verified": True},
        }
    )
    kept = await service.save(malicious)
    assert (
        kept.connectors
        and kept.diagram_notes
        and kept.reviewed_bus_mappings == data.reviewed_bus_mappings
    )
    assert not kept.validation
