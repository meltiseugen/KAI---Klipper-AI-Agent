import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from kai_agent.application.knowledge import PrinterKnowledge
from kai_agent.application.knowledge_refresh import component_sources
from kai_agent.domain.knowledge import ComponentIdentity, KnowledgeConflict, KnowledgeSetup
from kai_agent.knowledge.firmware import firmware_sources
from kai_agent.knowledge.sources import component_key, document_source
from kai_agent.providers.knowledge import OpenAIKnowledgeResearcher, public_identity
from tests.knowledge_helpers import documents, setup
from tests.test_knowledge_storage import repository


def test_integrated_components_validate_board_relationships_and_supply_public_context():
    board = setup().components[0]
    sensor = ComponentIdentity(
        role="accelerometer",
        category="device",
        integrated_into=board.role,
        details="Custom sensor mounting",
    )
    data = KnowledgeSetup(components=[board, sensor])
    identity = public_identity(sensor, data)
    assert identity["containing_board_model"] == board.model
    assert identity["user_details"] == sensor.details
    assert component_key(sensor) != component_key(sensor.copy(update={"integrated_into": ""}))
    for components in (
        [sensor],
        [sensor, board.copy(update={"category": "device"})],
        [
            board.copy(update={"integrated_into": sensor.role}),
            sensor.copy(update={"category": "board"}),
        ],
    ):
        with pytest.raises(ValidationError):
            KnowledgeSetup(components=components)


@pytest.mark.asyncio
async def test_legacy_sources_discovery_fallback_and_explicit_removal():
    data = setup()
    board = data.components[0]
    board.reference_urls = ["http://invalid.example/", "https://example.org/retained"]
    ref = document_source(board, board.reference_urls[1])
    assert await component_sources(board, data, None) == ([ref], False)
    search = SimpleNamespace(discover=AsyncMock(side_effect=ValueError("unavailable")))
    assert await component_sources(board, data, search) == ([ref], True)
    data.dismissed_documents[ref.id] = ref.url
    with pytest.raises(ValueError):
        await component_sources(board, data, None)
    with pytest.raises(ValueError, match="unavailable"):
        await component_sources(board, data, search)
    search_result = SimpleNamespace(search=AsyncMock(return_value=SimpleNamespace(citations=[])))
    await OpenAIKnowledgeResearcher(SimpleNamespace(), search_result).discover(board, data)
    assert ref.url in search_result.search.call_args.args[0]


@pytest.mark.asyncio
async def test_component_job_guards_reference_reviews_and_retained_history(tmp_path):
    store = repository(tmp_path)
    service = PrinterKnowledge(store, SimpleNamespace(), {})
    data = setup().copy(update={"components": setup().components[:1]})
    saved = await service.save(data)
    for role in ("missing",):
        with pytest.raises(KnowledgeConflict):
            await service.start_refresh(role)
    saved.components[0].model = ""
    saved = await service.save(saved)
    with pytest.raises(KnowledgeConflict):
        await service.start_refresh("mainboard")
    service.job["component_role"] = "mainboard"
    service._task = asyncio.create_task(asyncio.Event().wait())
    assert (await service.start_refresh("mainboard"))["component_role"] == "mainboard"
    with pytest.raises(KnowledgeConflict):
        await service.start_refresh("other")
    await service.aclose()
    doc = documents()[0].copy(update={"id": "d" * 32})
    store.save_document(doc, b"cached")
    with pytest.raises(KnowledgeConflict):
        await service.review_reference(doc.id, "changed", saved.revision)
    with pytest.raises(KnowledgeConflict):
        store.update_reference(saved, doc.copy(update={"digest": "changed"}), delete=False)
    with pytest.raises(KnowledgeConflict):
        store.update_reference(saved, doc.copy(update={"id": "missing"}), delete=False)
    confirmed = await service.review_reference(doc.id, doc.digest, saved.revision)
    assert confirmed.confirmed_documents[doc.id] == doc.digest
    # A source change invalidates the confirmation but keeps the previous bytes.
    store.save_document(doc.copy(update={"digest": "new"}), b"new")
    assert (await service.status())["documents"][0]["confirmation_stale"]
    deleted = await service.review_reference(doc.id, "new", confirmed.revision, delete=True)
    assert doc.id in deleted.dismissed_documents and doc.id not in deleted.confirmed_documents
    assert not store.documents() and store.original(doc.id) is None
    # Explicitly dismissed cached items remain hidden, even if old bytes are restored externally.
    store.save_document(doc, b"cached")
    assert not (await service.read())[1]


@pytest.mark.asyncio
async def test_global_refresh_honors_removed_firmware_sources(tmp_path):
    data = setup().copy(
        update={
            "components": [],
            "firmware_repository": "https://github.com/Klipper3d/klipper",
            "firmware_commit": "a" * 40,
        }
    )
    refs = firmware_sources(data)
    data.dismissed_documents = {refs[0].id: refs[0].url}
    store = repository(tmp_path)
    store.save_setup(data)
    fetch = AsyncMock(return_value=(b"reference", "reference", "text"))
    service = PrinterKnowledge(store, SimpleNamespace(fetch=fetch), {})
    await service.start_refresh()
    await service._task
    assert fetch.await_count == len(refs) - 1
    assert all(call.args[0].id != refs[0].id for call in fetch.await_args_list)


@pytest.mark.asyncio
async def test_repository_listing_failure_preserves_other_useful_references(tmp_path):
    data = setup().copy(update={"components": setup().components[:1]})
    board = data.components[0]
    board.reference_urls = ["https://example.org/manual"]
    root = document_source(board, "https://github.com/vendor/board")
    research = SimpleNamespace(
        discover=AsyncMock(return_value=[root]), extract=AsyncMock(return_value=[])
    )

    async def expand(source):
        if source.url == root.url:
            raise ValueError("Repository listing unavailable")
        return [source]

    resolver = SimpleNamespace(resolve=expand)
    fetch = AsyncMock(return_value=(b"manual", "Readable manual", "text"))
    service = PrinterKnowledge(
        repository(tmp_path), SimpleNamespace(fetch=fetch), {}, research, resolver=resolver
    )
    await service.save(data)
    await service.start_refresh("mainboard")
    await service._task
    assert service.job["state"] == "partial"
    assert "repository traversal incomplete" in service.job["changes"][0]
    assert [doc.url for doc in (await service.read())[1]] == board.reference_urls
