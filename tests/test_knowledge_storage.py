import asyncio
import sqlite3
from contextlib import closing
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from klipperai_agent.application.knowledge import PrinterKnowledge
from klipperai_agent.domain.knowledge import KnowledgeConflict, KnowledgeSetup
from klipperai_agent.infrastructure.knowledge import SqliteKnowledgeRepository
from klipperai_agent.knowledge.sources import document_source
from tests.knowledge_helpers import documents, researcher, setup


def repository(tmp_path, printer="printer-a"):
    return SqliteKnowledgeRepository(tmp_path / "data", printer, (tmp_path / "config",))


def test_repository_versions_restart_isolation_and_lost_updates(tmp_path):
    store = repository(tmp_path)
    assert store.setup() is None and store.documents() == [] and store.original("missing") is None
    first = store.save_setup(setup())
    assert first.revision == 1
    assert repository(tmp_path).setup() == first
    with pytest.raises(KnowledgeConflict):
        store.save_setup(setup())
    assert store.save_setup(first).revision == 2
    doc = documents()[0]
    for version in range(3):
        store.save_document(doc.copy(update={"digest": str(version)}), str(version).encode())
    # Updating the date of an unchanged source does not consume a version slot.
    store.save_document(doc.copy(update={"digest": "2", "fetched_at": "new date"}), b"2")
    assert store.documents()[0].digest == "2" and store.documents()[0].fetched_at == "new date"
    assert store.original(doc.id) == b"2"
    assert store.original(doc.id, "1") == b"1" and store.original(doc.id, "0") is None
    with closing(sqlite3.connect(tmp_path / "data/knowledge.sqlite3")) as db:
        assert db.execute("SELECT count(*) FROM documents").fetchone()[0] == 2
    other = repository(tmp_path, "printer-b")
    assert other.setup() is None and other.documents() == [] and other.original(doc.id) is None
    with pytest.raises(ValueError, match="bounds"):
        store.save_document(doc, b"x" * (8 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="bounds"):
        store.save_document(doc.copy(update={"content": "x" * 300001}), b"small")


def test_repository_rejects_printer_dirs_and_redirected_files(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="outside printer"):
        SqliteKnowledgeRepository(tmp_path / "config/knowledge", "p", (tmp_path / "config",))
    store = repository(tmp_path)
    original = tmp_path / "printer.cfg"
    original.write_text("keep this", encoding="utf-8")
    auxiliary = tmp_path / "data/knowledge.sqlite3-journal"
    auxiliary.hardlink_to(original)
    with pytest.raises(ValueError, match="redirected"):
        store.setup()
    assert original.read_text(encoding="utf-8") == "keep this"
    auxiliary.unlink()
    monkeypatch.setattr(Path, "is_symlink", lambda path: path.name.endswith("-wal"))
    with pytest.raises(ValueError, match="redirected"):
        store.documents()


@pytest.mark.asyncio
async def test_build_refresh_cache_failure_and_profile_changes(tmp_path):
    store = repository(tmp_path)
    fetch = AsyncMock(return_value=(b"reference v1", "reference v1", "text"))
    service = PrinterKnowledge(
        store, SimpleNamespace(fetch=fetch), {"mainboard": "BTT Manta E3EZ"}, researcher()
    )
    status = await service.status()
    assert status["setup"]["components"][0]["model"] == "BTT Manta E3EZ"
    saved = await service.save(setup())
    assert saved.updated_at and saved.revision == 1
    assert not (await service.read())[2]
    assert (await service.start_refresh())["state"] == "running"
    await service._task
    assert service.job["state"] == "completed" and service.job["total"] == 3
    assert all("added" in item for item in service.job["changes"])
    assert len(store.documents()) == 3
    document_id = document_source(saved.components[0], "https://example.org/mainboard").id
    assert (await service.original(document_id))[1] == b"reference v1"
    assert await service.original("no-document") is None
    await service.start_refresh()
    await service._task
    assert all("unchanged" in item for item in service.job["changes"])
    fetch.return_value = (b"reference v2", "reference v2", "text")
    await service.start_refresh()
    await service._task
    assert all("updated" in item for item in service.job["changes"])
    assert store.documents()[0].digest == sha256(b"reference v2").hexdigest()
    fetch.side_effect = TimeoutError("private details")
    await service.start_refresh()
    await service._task
    assert service.job["state"] == "partial"
    assert "private details" not in str(await service.status())
    assert len(store.documents()) == 3
    assert (await service.original(document_id))[1] == b"reference v2"
    restarted = PrinterKnowledge(
        repository(tmp_path), SimpleNamespace(fetch=fetch), {"mainboard": "Different board"}
    )
    assert (await restarted.read())[2]
    assert "Needs details" in str((await restarted.status())["components"])
    await service.aclose()


@pytest.mark.asyncio
async def test_refresh_dedup_lock_cancellation_and_empty_catalog(tmp_path):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def fetch(source):
        entered.set()
        await release.wait()
        return b"x", "x", "text"

    service = PrinterKnowledge(repository(tmp_path), SimpleNamespace(fetch=fetch), {}, researcher())
    await service.start_refresh()
    await service._task
    assert "Enter component models" in service.job["message"]
    await service.save(setup())
    await service.start_refresh()
    await entered.wait()
    original_task = service._task
    assert (await service.start_refresh())["state"] == "running"
    assert service._task is original_task
    with pytest.raises(KnowledgeConflict, match="Wait"):
        await service.save(setup())
    await service.aclose()
    assert original_task.cancelled()
    await PrinterKnowledge(repository(tmp_path, "other"), SimpleNamespace(fetch=fetch), {}).aclose()


@pytest.mark.asyncio
async def test_review_requires_current_identity_and_evidence_then_invalidates_on_change(tmp_path):
    store = repository(tmp_path)
    doc = documents()[0]
    research = researcher()
    research.extract.return_value = doc.fan_mappings
    fetch = AsyncMock(return_value=(doc.content.encode(), doc.content, "text"))
    service = PrinterKnowledge(store, SimpleNamespace(fetch=fetch), {}, research)
    initial = setup().copy(update={"components": setup().components[:1]})
    saved = await service.save(initial)
    assert saved.reviewed_fan_mappings == {}  # Client cannot self-approve evidence in a save.
    for role, signature, revision in (
        ("missing", "x", 1),
        ("mainboard", "x", 0),
        ("mainboard", "x", 1),
    ):
        with pytest.raises(KnowledgeConflict):
            await service.review_mappings(role, signature, revision)
    await service.start_refresh()
    await service._task
    status = await service.status()
    assert not status["components"][0]["fan_mappings_reviewed"]
    signature = status["components"][0]["fan_evidence"]["signature"]
    saved = await service.review_mappings("mainboard", signature, 1)
    assert (
        saved.revision == 2 and (await service.status())["components"][0]["fan_mappings_reviewed"]
    )
    await service.start_refresh()
    await service._task
    assert (await service.status())["components"][0]["fan_mappings_reviewed"]
    assert research.extract.await_count == 1  # Unchanged evidence needs no new extraction.
    saved.components[0].connection = "UART"
    saved = await service.save(saved)
    assert not (await service.status())["components"][0]["fan_mappings_reviewed"]
    # Failed extraction of a changed document must never leave the old approval in force.
    fetch.return_value = (b"changed", "changed", "text")
    research.extract.side_effect = ValueError("provider private detail")
    await service.start_refresh()
    await service._task
    assert service.job["state"] == "partial"
    assert not (await service.status())["components"][0]["fan_mappings_reviewed"]
    saved.components[0].revision = "new board revision"
    await service.save(saved)
    assert store.documents() == []
    assert await service.original(status["documents"][0]["id"]) is None


@pytest.mark.asyncio
async def test_reference_urls_without_provider_missing_discovery_and_job_deadline(
    tmp_path, monkeypatch
):
    import klipperai_agent.application.knowledge as service_module

    fetch = AsyncMock(return_value=(b"reference", "reference", "text"))
    service = PrinterKnowledge(repository(tmp_path), SimpleNamespace(fetch=fetch), {})
    data = setup().copy(update={"components": setup().components[:1]})
    data.components[0].reference_urls = ["https://example.org/manual"]
    saved = await service.save(data)
    await service.start_refresh()
    await service._task
    assert (
        service.job["state"] == "completed" and not (await service.status())["automatic_research"]
    )
    saved.components[0].reference_urls = []
    saved = await service.save(saved)
    await service.start_refresh()
    await service._task
    assert service.job["state"] == "partial"
    service.researcher = researcher()
    service.researcher.discover.return_value = []
    service.researcher.discover.side_effect = None
    await service.start_refresh()
    await service._task
    assert service.job["state"] == "partial" and len((await service.read())[1]) == 1

    async def timeout(awaitable, **kwargs):
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(service_module.asyncio, "wait_for", timeout)
    await service._run(KnowledgeSetup(), [], {})
    assert service.job["state"] == "partial" and "time limit" in service.job["message"]


def test_cache_retention_and_quota_are_per_printer_and_transactional(tmp_path):
    store, other = repository(tmp_path), repository(tmp_path, "other")
    doc = documents()[0]
    other.save_document(doc, b"other")
    for index in range(72):
        store.save_document(doc.copy(update={"id": str(index)}), b"small")
    with pytest.raises(ValueError, match="quota"):
        store.save_document(doc.copy(update={"id": "overflow"}), b"small")
    assert len(store.documents()) == 72 and store.original("overflow") is None
    store.retain_sources(doc.component_key, {"0"})
    assert [item.id for item in store.documents()] == ["0"]
    store.retain_components(set())
    assert store.documents() == [] and other.original(doc.id) == b"other"
