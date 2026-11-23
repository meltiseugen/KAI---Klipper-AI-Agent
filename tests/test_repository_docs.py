import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kai_agent.application.knowledge import PrinterKnowledge
from kai_agent.application.knowledge_refresh import component_sources
from kai_agent.domain.knowledge import DocumentSource
from kai_agent.infrastructure.repository_docs import RepositoryDocumentationResolver
from kai_agent.knowledge.identity import reference_metadata
from kai_agent.knowledge.repositories import reference_paths, repository_location
from kai_agent.knowledge.retrieval import search_documents
from kai_agent.knowledge.sources import document_source
from tests.knowledge_helpers import documents, setup
from tests.test_knowledge_storage import repository


def tree(*paths):
    return {"tree": [{"path": p, "type": "blob", "size": 100} for p in paths]}


def test_repository_indexes_and_reference_selection():
    assert repository_location("https://github.com/vendor/board.git") == (
        "vendor/board",
        "HEAD",
        "",
    )
    assert repository_location("https://github.com/vendor/board/tree/main/Hardware") == (
        "vendor/board",
        "main",
        "Hardware",
    )
    assert repository_location("https://github.com/vendor/board/tree/fix%2Fdocs") == (
        "vendor/board",
        "fix/docs",
        "",
    )
    for url in (
        "https://example.org/board",
        "https://github.com/vendor",
        "https://github.com/a!/b",
        "https://github.com/v/b/blob/main/manual.pdf",
        "https://github.com/v/b/tree/main//Hardware",
    ):
        assert repository_location(url) is None
    listing = tree(
        "User Manual.pdf",
        "Hardware/User Manual.pdf",
        "Firmware/Klipper/generic-board.cfg",
        "Firmware/Klipper/printer-example.cfg",
        "Hardware/board-SCH.pdf",
        "Hardware/board-PIN.png",
        "Hardware/board-Interface.png",
        "Firmware/README.md",
        "Firmware/bootloader.bin",
        "3D/User Manual.pdf",
        "CAD/pin.png",
        "archive.zip",
        "misc.pdf",
        "Hardware/../pin.png",
        "/pin.png",
    )
    listing["tree"] += [
        None,
        {"type": "tree"},
        {"type": "blob", "path": 1, "size": 1},
        {"type": "blob", "path": "huge-manual.pdf", "size": 9 * 1024**2},
    ]
    paths = reference_paths(listing)
    assert paths[:2] == [
        "Firmware/Klipper/generic-board.cfg",
        "Firmware/Klipper/printer-example.cfg",
    ]
    assert "Hardware/User Manual.pdf" in paths and "User Manual.pdf" not in paths
    assert len(paths) == 7
    assert reference_paths(listing, "Hardware") == [p for p in paths if p.startswith("Hardware/")]
    for bad in (
        {"truncated": True, **listing},
        {},
        tree("file.bin"),
        tree(*(f"{n}.cfg" for n in range(65))),
    ):
        with pytest.raises(ValueError):
            reference_paths(bad)


@pytest.mark.asyncio
async def test_resolver_fetches_tree_and_pins_real_files_without_caching_html():
    board = setup().components[0]
    source = document_source(board, "https://github.com/vendor/board")
    fetch = AsyncMock(
        side_effect=[
            (b"", json.dumps({"sha": "a" * 40}), "text"),
            (
                b"",
                json.dumps(tree("Hardware/User Manual.pdf", "Firmware/Klipper/generic-board.cfg")),
                "text",
            ),
        ]
    )
    resolver = RepositoryDocumentationResolver(SimpleNamespace(fetch=fetch))
    refs = await resolver.resolve(source)
    assert len(refs) == 2 and refs[0].component_key == source.component_key
    assert refs[0].url.endswith("/HEAD/Firmware/Klipper/generic-board.cfg")
    assert refs[1].download_url.endswith("/" + "a" * 40 + "/Hardware/User%20Manual.pdf")
    assert refs[1].repository_commit == "a" * 40
    assert fetch.await_args_list[0].args[0].url.endswith("/commits/HEAD")
    assert fetch.await_args_list[1].args[0].url.endswith("/git/trees/" + "a" * 40 + "?recursive=1")
    assert await resolver.resolve(DocumentSource("x", "Manual", "https://example.org/manual")) == [
        DocumentSource("x", "Manual", "https://example.org/manual")
    ]
    for data in ([], {"sha": "HEAD"}, {"sha": 1}):
        fetch.side_effect = [(b"", json.dumps(data), "text")]
        with pytest.raises(ValueError):
            await resolver.resolve(source)
    fetch.side_effect = [(b"", "invalid json", "text")]
    with pytest.raises(ValueError):
        await resolver.resolve(source)


@pytest.mark.asyncio
async def test_expansion_dismissal_partial_failure_and_download_metadata(tmp_path):
    data = setup().copy(update={"components": setup().components[:1]})
    board = data.components[0]
    root = document_source(board, "https://github.com/vendor/board")
    leaf = document_source(
        board, "https://raw.githubusercontent.com/vendor/board/HEAD/Hardware/manual.pdf"
    )
    leaf = replace(
        leaf,
        download_url=leaf.url.replace("/HEAD/", "/" + "a" * 40 + "/"),
        repository_commit="a" * 40,
    )
    research = SimpleNamespace(
        discover=AsyncMock(return_value=[root, root]), extract=AsyncMock(return_value=[])
    )
    resolver = SimpleNamespace(resolve=AsyncMock(return_value=[leaf]))
    refs, failed = await component_sources(board, data, research, resolver)
    assert refs == [leaf] and not failed
    resolver.resolve.assert_awaited_once()
    data.dismissed_documents[leaf.id] = leaf.url
    assert await component_sources(board, data, research, resolver) == ([], False)
    data.dismissed_documents.clear()
    resolver.resolve.side_effect = ValueError("rate limited")
    assert await component_sources(board, data, research, resolver) == ([], True)
    resolver.resolve.side_effect = None
    fetch = AsyncMock(return_value=(b"manual", "Readable manual pin PB1", "text"))
    service = PrinterKnowledge(
        repository(tmp_path), SimpleNamespace(fetch=fetch), {}, research, resolver=resolver
    )
    await service.save(data)
    await service.start_refresh("mainboard")
    await service._task
    assert service.job["state"] == "completed"
    assert fetch.call_args.args[0] == leaf
    doc = (await service.read())[1][0]
    assert "a" * 40 in doc.version
    assert doc.id == leaf.id and doc.component_key == leaf.component_key
    # Existing, even confirmed, homepage records remain preserved but cannot supply navigation as evidence.
    old = documents()[0].copy(update={"url": root.url, "content": "GitHub navigation pin PB1"})
    assert search_documents([old], "pin", {old.id}) == []
    assert "Repository index only" in reference_metadata(data, old)["excerpt"]
