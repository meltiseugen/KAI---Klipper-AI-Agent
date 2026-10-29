"""Resource regressions use real files/SQLite and observable work, not timing gates."""

import asyncio
import sqlite3
from contextlib import closing
from unittest.mock import AsyncMock

import pytest

from klipperai_agent.config.collector import MAX_CONFIG_CHARS, ConfigCollector
from klipperai_agent.config.models import ConfigDocument, ConfigReadError
from klipperai_agent.contracts.api import ChatRequest
from klipperai_agent.domain.investigation import (
    Evidence,
    Investigation,
    InvestigationResult,
    InvestigationTurn,
    PendingInvestigation,
)
from klipperai_agent.domain.repositories import InvestigationConflict
from klipperai_agent.infrastructure.host.logs import MAX_LOG_FILES, MAX_TAIL_BYTES, HostLogCollector
from klipperai_agent.infrastructure.investigations import SqliteInvestigationRepository
from klipperai_agent.web.streaming import ChatEventStream
from tests.test_agent_integration import agent_service as agent_service


def test_log_byte_limit_retains_complete_recent_faults_and_reports_missing_lines(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    path = logs / "klippy.log"
    path.write_bytes(b"x" * (MAX_TAIL_BYTES * 8) + b"\nLost communication with MCU\n")
    excerpt, partial = HostLogCollector._read_last_lines(path, 100)
    assert partial and excerpt == "Lost communication with MCU"
    path.write_bytes(b"x" * (MAX_TAIL_BYTES * 8))
    artifacts, notes = HostLogCollector(tmp_path).collect()
    assert not artifacts
    assert any("byte-limited" in note for note in notes)


def test_excess_logs_are_bounded_and_keep_core_printer_evidence(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "klippy.log").write_text("Important printer fault\n")
    for index in range(MAX_LOG_FILES + 4):
        (logs / f"extra-{index}.log").write_text("Other service\n")
    artifacts, notes = HostLogCollector(tmp_path).collect()
    assert len(artifacts) == MAX_LOG_FILES
    assert any(item.label == "klippy.log" for item in artifacts)
    assert any("other current logs omitted" in note for note in notes)


def test_oversized_config_is_a_gap_and_cannot_be_expanded(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "printer.cfg").write_text("[printer]\nkinematics: cartesian\n")
    (config / "large.cfg").write_text("x" * (MAX_CONFIG_CHARS + 1))
    collector = ConfigCollector(tmp_path, root_config_name="large.cfg")
    snapshot = collector.collect()
    assert not snapshot.documents
    assert any("exceeds the full-read limit" in note for note in snapshot.notes)
    with pytest.raises(ConfigReadError, match="full-read limit"):
        collector.read_collected_document(ConfigDocument("large.cfg", "", []))
    assert ConfigCollector(tmp_path).collect().root_file == "printer.cfg"


def test_standard_root_does_not_read_archived_configurations(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    (config / "printer.cfg").write_text("[printer]\nkinematics: cartesian\n")
    archive = config / "archive.cfg"
    archive.write_text("[printer]\n# archived, inactive configuration\n")
    original = type(archive).open

    def checked_open(path, *args, **kwargs):
        assert path != archive, "Inactive backups must not be read to discover the normal root"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(type(archive), "open", checked_open)
    assert len(ConfigCollector(tmp_path).collect().documents) == 1


def test_sidebar_summaries_never_query_turn_content_and_heartbeats_do_not_rewrite_it(tmp_path):
    store = SqliteInvestigationRepository(tmp_path / "own", protected_dirs=())
    record = Investigation(printer_id="p", title="Stored title")
    store.save_turn(record, InvestigationTurn(question="Q", result=InvestigationResult()))
    record = store.get("p", record.id)
    run = PendingInvestigation(
        message="Investigate", evidence=[Evidence(source="log", content="x" * 10000)]
    )
    store.runs.begin(record, run, "owner")
    with pytest.raises(InvestigationConflict, match="still running"):
        store.runs.begin(record, run, "other")
    with pytest.raises(InvestigationConflict):
        store.runs.checkpoint("p", record.id, run.id, "other", [])
    queries = []
    connect = store._connect

    def traced_connect():
        db = connect()
        db.set_trace_callback(queries.append)
        return db

    store._connect = traced_connect
    summary = store.summaries("p")[0]
    assert summary.title == "Stored title" and not summary.turns and summary.pending.id == run.id
    assert not any("FROM turns" in sql for sql in queries)
    with closing(sqlite3.connect(store._path)) as db, db:
        db.executescript("""
            CREATE TABLE writes (count INTEGER);
            INSERT INTO writes VALUES (0);
            CREATE TRIGGER checkpoint_content_write AFTER UPDATE OF content ON pending_runs
            BEGIN UPDATE writes SET count=count+1; END;
        """)
    store.runs.checkpoint("p", record.id, run.id, "owner")
    with closing(sqlite3.connect(store._path)) as db:
        assert db.execute("SELECT count FROM writes").fetchone()[0] == 0
    store.runs.checkpoint("p", record.id, run.id, "owner", run.evidence)
    with closing(sqlite3.connect(store._path)) as db:
        assert db.execute("SELECT count FROM writes").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_multiple_tabs_cannot_run_parallel_investigations_and_cancellation_frees_capacity(
    agent_service,
):
    started, release = asyncio.Event(), asyncio.Event()

    async def slow(*args, **kwargs):
        started.set()
        await release.wait()
        return {"response_text": "Finished"}

    agent_service.agent_workflow.ainvoke = AsyncMock(side_effect=slow)
    session = await agent_service.create_ui_session()
    request = ChatRequest(session_id=session.session_id, message="Investigate")
    running = asyncio.create_task(agent_service.chat(request))
    await started.wait()
    try:
        with pytest.raises(InvestigationConflict, match="Another investigation"):
            await agent_service.chat(request)
        events = "".join([event async for event in ChatEventStream(agent_service).events(request)])
        assert "Another investigation" in events and '"status": "not_used"' in events
        assert agent_service.agent_workflow.ainvoke.await_count == 1
    finally:
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
    release.set()
    assert (await agent_service.chat(request)).response == "Finished"
