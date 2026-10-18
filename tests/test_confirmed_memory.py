from __future__ import annotations

import sqlite3
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from test_investigations import persistent_service as persistent_service
from test_investigations import repository

import klipperai_agent.web.app as app_module
from klipperai_agent.application.investigations import InvestigationMemory
from klipperai_agent.contracts.api import ChatRequest
from klipperai_agent.domain.investigation import (
    ConfirmedMemory,
    Investigation,
    InvestigationResult,
    InvestigationTurn,
)
from klipperai_agent.domain.repositories import InvestigationConflict
from klipperai_agent.runtime.settings import Settings


@pytest.mark.asyncio
async def test_confirmed_statements_are_dated_scoped_and_never_inferred(
    tmp_path, persistent_service
):
    service, model = persistent_service
    session = await service.create_ui_session()
    first = await service.chat(ChatRequest(session_id=session.session_id, message="fan proposal"))
    memory = service.investigations
    assert await memory.confirmed() == []  # A confident model answer cannot create a fact.
    record = await memory.get(first.thread_id)
    evidence = record.turns[0].result.evidence[-1]
    fact = await memory.confirm(
        ConfirmedMemory(kind="fact", content="Fan connector checked", investigation_id=record.id),
        [evidence.id],
    )
    preference = await memory.confirm(
        ConfirmedMemory(kind="preference", content="Use metric units"), []
    )
    resolution = await memory.confirm(
        ConfirmedMemory(
            kind="resolution",
            content="Fan incident resolved by replacing the connector",
            investigation_id=record.id,
        ),
        [],
    )
    service.investigations = InvestigationMemory(repository(tmp_path), "p")
    saved = await service.investigations.confirmed()
    assert {item.kind for item in saved} == {"fact", "preference", "resolution"}
    assert saved[-1].evidence[0] == evidence and fact.confirmed_at
    reply = await service.chat(ChatRequest(session_id=session.session_id, message="fan again"))
    assert {item.source for item in reply.memory_sources} >= {
        "user-confirmed:fact",
        "user-confirmed:preference",
        "user-confirmed:resolution",
    }
    assert "dated user statement" in str(model.requests[-1]["historical_evidence"])
    isolated = InvestigationMemory(repository(tmp_path), "p", cross_chat=False)
    assert await isolated.recall(await isolated.open(None, "fan"), "fan") == []
    assert fact.id in {e.id for e in await isolated.recall(record, "continue")}
    other = InvestigationMemory(repository(tmp_path), "other")
    assert await other.confirmed() == []
    await other.forget_confirmed(preference.id)
    assert len(await memory.confirmed()) == 3
    await memory.forget_confirmed(preference.id)
    await memory.delete(record.id)
    assert await memory.confirmed() == []
    assert resolution.id not in {
        e.id for e in await memory.recall(await memory.open(None, "fan"), "fan")
    }


def test_confirmed_retention_redaction_capacity_and_deleted_source(tmp_path):
    store = repository(tmp_path)
    investigation = Investigation(printer_id="p", title="Incident")
    store.save_turn(investigation, InvestigationTurn(question="fan", result=InvestigationResult()))
    item = ConfirmedMemory(
        kind="resolution",
        content="password=do-not-store\nFan replaced",
        investigation_id=investigation.id,
    )
    store.confirmed.save("p", item)
    with closing(sqlite3.connect(tmp_path / "own-data/investigations.sqlite3")) as db, db:
        db.execute("UPDATE investigations SET updated_at='2000-01-01'")
    assert store.get("p", investigation.id) is None
    assert "do-not-store" not in store.confirmed.list("p")[0].content
    for index in range(99):
        store.confirmed.save("p", ConfirmedMemory(kind="fact", content=str(index)))
    with pytest.raises(InvestigationConflict, match="full"):
        store.confirmed.save("p", ConfirmedMemory(kind="fact", content="overflow"))
    with pytest.raises(InvestigationConflict, match="deleted"):
        store.confirmed.save("other", item)


def test_memory_api_requires_explicit_confirmation_and_valid_evidence(
    monkeypatch, tmp_path, persistent_service
):
    service, _ = persistent_service
    settings = Settings(data_dir=tmp_path / "own-data", printer_data_root=tmp_path)
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        app_module,
        "build_container",
        lambda _: SimpleNamespace(
            chat_service=service, sessions=service.sessions, aclose=AsyncMock()
        ),
    )
    original = (tmp_path / "config/printer.cfg").read_bytes()
    with TestClient(app_module.create_app()) as client:
        session = client.post("/api/ui-sessions").json()["session_id"]
        query = {"session_id": session}
        payload = {
            "session_id": session,
            "kind": "fact",
            "content": "Physical fan checked",
            "confirmed": True,
        }
        for change in [
            {"confirmed": False},
            {"confirmed": "true"},
            {"content": "  "},
            {"kind": "guess"},
            {"confirmed_at": "yesterday"},
        ]:
            assert client.post("/api/memory", json={**payload, **change}).status_code == 422
        assert (
            client.post(
                "/api/memory",
                json={key: value for key, value in payload.items() if key != "confirmed"},
            ).status_code
            == 422
        )
        assert client.get("/api/memory", params={"session_id": "bad"}).status_code == 403
        assert (
            client.post("/api/memory", json={**payload, "investigation_id": "missing"}).status_code
            == 400
        )
        assert (
            client.post("/api/memory", json={**payload, "evidence_ids": ["fake"]}).status_code
            == 400
        )
        answer = client.post("/api/chat", json={"session_id": session, "message": "fan"}).json()
        record = client.get(f"/api/investigations/{answer['thread_id']}", params=query).json()
        observation = record["turns"][0]["result"]["evidence"][0]
        saved = client.post(
            "/api/memory",
            json={**payload, "investigation_id": record["id"], "evidence_ids": [observation["id"]]},
        )
        assert saved.status_code == 201
        assert saved.json()["evidence"][0] == observation
        assert client.get("/api/memory", params=query).json()[0]["id"] == saved.json()["id"]
        assert client.delete(f"/api/memory/{saved.json()['id']}", params=query).status_code == 204
        service.investigations.confirm = AsyncMock(
            side_effect=InvestigationConflict("Memory is full")
        )
        assert client.post("/api/memory", json=payload).status_code == 409
        service.investigations = None
        assert client.get("/api/memory", params=query).status_code == 404
    assert (tmp_path / "config/printer.cfg").read_bytes() == original
