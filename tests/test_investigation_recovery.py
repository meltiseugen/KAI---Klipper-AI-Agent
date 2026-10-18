from __future__ import annotations

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from test_investigations import ConfigModel, repository
from test_investigations import persistent_service as persistent_service

import klipperai_agent.web.app as app_module
from klipperai_agent.agent.models import AgentLimits
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.application.investigations import InvestigationMemory
from klipperai_agent.application.recovery import InvestigationRecovery, with_lease
from klipperai_agent.application.sessions import InMemorySessionStore
from klipperai_agent.contracts.api import ChatRequest
from klipperai_agent.domain.investigation import (
    Evidence,
    Investigation,
    InvestigationResult,
    InvestigationTurn,
    PendingInvestigation,
    utc_now,
)
from klipperai_agent.domain.repositories import InvestigationConflict
from klipperai_agent.runtime.settings import Settings


async def eventually(read, predicate):
    for _ in range(200):
        value = await read()
        if predicate(value):
            return value
        await asyncio.sleep(0.01)
    raise AssertionError("Expected recovery state did not arrive")


@pytest.mark.asyncio
async def test_interrupted_request_resumes_once_with_fresh_config_and_dated_observations(
    tmp_path, persistent_service
):
    service, _ = persistent_service
    waiting = asyncio.Event()

    class PausedModel(ConfigModel):
        async def respond(self, conversation, tools):
            if len(conversation) > 2:
                waiting.set()
                await asyncio.Event().wait()
            turn = await super().respond(conversation, tools)
            turn.output.append(
                {"type": "reasoning", "encrypted_content": "private-reasoning-must-not-persist"}
            )
            return turn

    service.agent_workflow = AgentWorkflow(PausedModel(), SimpleNamespace(), AgentLimits())
    session = await service.create_ui_session()
    request = ChatRequest(
        session_id=session.session_id,
        thread_id="restart-me",
        message="fan proposal",
        history=[{"role": "user", "text": "Earlier context"}],
    )
    task = asyncio.create_task(service.chat(request))
    await asyncio.wait_for(waiting.wait(), 3)
    pending = await service.investigations.get("restart-me")
    assert pending.pending.evidence and not pending.turns
    with pytest.raises(InvestigationConflict, match="running"):
        await service.chat(request)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    raw = (tmp_path / "own-data/investigations.sqlite3").read_bytes()
    assert (
        b"private-reasoning-must-not-persist" not in raw and session.session_id.encode() not in raw
    )
    config = tmp_path / "config/printer.cfg"
    config.write_text("[printer]\nkinematics: cartesian\n[fan]\npin: PA2\n")
    manual_bytes = config.read_bytes()
    model = ConfigModel()
    restarted = replace(
        service,
        sessions=InMemorySessionStore(600),
        investigations=InvestigationMemory(repository(tmp_path), "p"),
        agent_workflow=AgentWorkflow(model, SimpleNamespace(), AgentLimits()),
    )
    worker = InvestigationRecovery(restarted.investigations, restarted.resume, poll_seconds=0.01)
    worker.start()
    try:
        saved = await eventually(
            lambda: restarted.investigations.get("restart-me"), lambda r: bool(r.turns)
        )
        assert saved.pending is None and len(saved.turns) == 1
        assert saved.turns[0].question == "fan proposal"
        assert "Earlier context" in model.requests[0]["recent_conversation"]
        assert "PA1" in str(model.requests[0]["historical_evidence"])
        assert "PA2" in str(model.requests[0]["active_config"])
        assert {e.id for e in pending.pending.evidence} <= {
            e.id for e in saved.turns[0].result.evidence
        }
        assert config.read_bytes() == manual_bytes
        assert await restarted.investigations.claim("second-worker", utc_now()) is None
    finally:
        await worker.aclose()


def test_run_claim_is_atomic_scoped_and_completion_cannot_resurrect_deleted_chat(tmp_path):
    store = repository(tmp_path)
    record = Investigation(printer_id="p", title="Fan")
    run = PendingInvestigation(message="fan", evidence=[Evidence(source="initial", content="old")])
    store.runs.begin(record, run, "original")
    record.pending = run
    assert store.runs.claim("p", "other", utc_now()) is None
    store.runs.release("different-printer", "original")
    assert store.runs.claim("p", "other", utc_now()) is None
    store.runs.release("p", "original")
    assert store.runs.claim("p", "other", "2000-01-01") is None
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(
            pool.map(lambda owner: store.runs.claim("p", owner, utc_now()), ["one", "two"])
        )
    assert claims.count(record.id) == 1
    owner = "one" if claims[0] else "two"
    recovered = store.get("p", record.id)
    assert recovered.pending.attempts == 1
    with pytest.raises(InvestigationConflict):
        store.runs.checkpoint("p", record.id, run.id, "original")
    evidence = [Evidence(source="config", content=f"fan {index}") for index in range(25)]
    store.runs.checkpoint("p", record.id, run.id, owner, evidence)
    store.runs.checkpoint("p", record.id, run.id, owner, evidence[-1:])
    store.runs.checkpoint("p", record.id, run.id, owner)
    assert len(store.get("p", record.id).pending.evidence) == 24
    turn = InvestigationTurn(question="fan", result=InvestigationResult())
    with pytest.raises(InvestigationConflict, match="finish"):
        store.save_turn(record, turn)
    with pytest.raises(InvestigationConflict):
        store.save_turn(record, turn, "original")
    store.delete("p", record.id)
    with pytest.raises(InvestigationConflict):
        store.save_turn(record, turn, owner)
    assert store.get("p", record.id) is None


def test_run_capacity_and_expired_checkpoints_do_not_block_new_work(tmp_path):
    store = repository(tmp_path)
    for index in range(100):
        store.runs.begin(
            Investigation(printer_id="p", title=str(index)),
            PendingInvestigation(message="fan"),
            "owner",
        )
    with pytest.raises(InvestigationConflict, match="Too many"):
        store.runs.begin(
            Investigation(printer_id="p", title="overflow"),
            PendingInvestigation(message="fan"),
            "owner",
        )
    with closing(sqlite3.connect(tmp_path / "own-data/investigations.sqlite3")) as db, db:
        db.execute("UPDATE investigations SET updated_at='2000-01-01'")
    assert store.runs.claim("p", "new", utc_now()) is None
    record = Investigation(printer_id="p", title="fresh")
    store.runs.begin(record, PendingInvestigation(message="fan"), "owner")
    assert len(store.recent("p")) == 1


@pytest.mark.asyncio
async def test_lease_heartbeat_cancels_work_when_chat_is_deleted(tmp_path):
    memory = InvestigationMemory(repository(tmp_path), "p")
    record = await memory.open(None, "fan")
    await memory.begin(record, PendingInvestigation(message="fan"), "owner")
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def operation():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    task = asyncio.create_task(
        with_lease(memory, record, "owner", operation(), heartbeat_seconds=0.01)
    )
    await started.wait()
    await asyncio.sleep(0.03)
    await memory.delete(record.id)
    with pytest.raises(InvestigationConflict):
        await task
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_recovery_stops_after_repeated_failures_and_preserves_cancelled_work(
    tmp_path, persistent_service
):
    service, _ = persistent_service
    record = await service.investigations.open(None, "fan")
    await service.investigations.begin(record, PendingInvestigation(message="fan"), "old")
    await service.investigations.release("old")
    service.agent_workflow = None
    service.diagnosis_graph = service.config_graph = SimpleNamespace(
        ainvoke=AsyncMock(side_effect=RuntimeError("provider failed"))
    )
    worker = InvestigationRecovery(service.investigations, service.resume, poll_seconds=0.01)
    worker.start()
    saved = await eventually(lambda: service.investigations.get(record.id), lambda r: bool(r.turns))
    await worker.aclose()
    assert saved.turns[0].result.agent_status == "limited" and saved.pending is None
    assert service.diagnosis_graph.ainvoke.await_count == 3
    # Shutdown cancellation retains the request for the next lifespan.
    blocked = await service.investigations.open(None, "next")
    await service.investigations.begin(blocked, PendingInvestigation(message="next"), "old")
    await service.investigations.release("old")
    started = asyncio.Event()

    async def wait_forever(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    service.diagnosis_graph.ainvoke = wait_forever
    worker = InvestigationRecovery(service.investigations, service.resume)
    worker.start()
    await asyncio.wait_for(started.wait(), 3)
    await worker.aclose()
    assert (await service.investigations.get(blocked.id)).pending
    assert await service.investigations.claim("new-startup", utc_now())


def test_app_lifespan_recovers_without_valid_old_session(monkeypatch, tmp_path, persistent_service):
    service, _ = persistent_service
    store = repository(tmp_path)
    record = Investigation(printer_id="p", title="fan")
    store.runs.begin(record, PendingInvestigation(message="fan"), "previous-process")
    # An expired lease models an ungraceful service/process termination.
    with closing(sqlite3.connect(tmp_path / "own-data/investigations.sqlite3")) as db, db:
        db.execute("UPDATE pending_runs SET lease_until='2000-01-01'")
    settings = Settings(data_dir=tmp_path / "own-data", printer_data_root=tmp_path)
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        app_module,
        "build_container",
        lambda _: SimpleNamespace(
            chat_service=service, sessions=service.sessions, aclose=AsyncMock()
        ),
    )
    with TestClient(app_module.create_app()) as client:
        session = client.post("/api/ui-sessions").json()["session_id"]
        saved = client.portal.call(
            eventually, lambda: service.investigations.get(record.id), lambda r: bool(r.turns)
        )
        assert saved.pending is None
        response = client.get(f"/api/investigations/{record.id}", params={"session_id": session})
        assert response.json()["turns"][0]["question"] == "fan"
        assert "private-reasoning" not in json.dumps(response.json())
