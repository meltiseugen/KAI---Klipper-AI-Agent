from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import klipperai_agent.web.app as app_module
from klipperai_agent.agent.models import AgentLimits, ModelTurn, ToolCall
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.application.chat import ChatService
from klipperai_agent.application.investigations import InvestigationMemory
from klipperai_agent.application.proposal_review import ProposalReviewService
from klipperai_agent.application.sessions import InMemorySessionStore
from klipperai_agent.config.collector import ConfigCollector
from klipperai_agent.domain.investigation import (
    Evidence,
    Investigation,
    InvestigationResult,
    InvestigationTurn,
)
from klipperai_agent.domain.messages import ChatHistoryMessage
from klipperai_agent.domain.repositories import InvestigationConflict
from klipperai_agent.infrastructure.investigations import SqliteInvestigationRepository
from klipperai_agent.profile.models import PrinterProfile
from klipperai_agent.runtime.settings import Settings


def repository(tmp_path):
    return SqliteInvestigationRepository(
        tmp_path / "own-data", protected_dirs=(tmp_path / "config",)
    )


def test_repository_restarts_isolates_printers_and_rejects_lost_updates(tmp_path):
    store = repository(tmp_path)
    investigation = Investigation(printer_id="printer-a", title="Fan")
    outcome = InvestigationResult(
        response_text="Check the fan",
        evidence=[Evidence(source="config", content="fan pin PA1")],
        agent_status="limited",
    )
    turn = InvestigationTurn(
        question="Fan issue?",
        result=outcome,
        imported_history=[ChatHistoryMessage(role="user", text="Previous message")],
    )
    store.save_turn(investigation, turn)
    restored = repository(tmp_path).get("printer-a", investigation.id)
    assert restored.revision == 1
    assert restored.turns[0].result.agent_status == "limited"
    assert [message.text for message in restored.history()] == [
        "Previous message",
        "Fan issue?",
        "Check the fan",
    ]
    assert restored.turns[0].result.evidence[0].id == outcome.evidence[0].id
    assert store.get("printer-b", investigation.id) is None
    assert store.recent("printer-b") == []
    with pytest.raises(InvestigationConflict):
        store.save_turn(investigation, turn)
    assert len(store.get("printer-a", investigation.id).turns) == 1
    store.delete("printer-b", investigation.id)
    assert store.get("printer-a", investigation.id)
    store.delete("printer-a", investigation.id)
    assert store.recent("printer-a") == []
    with closing(sqlite3.connect(tmp_path / "own-data/investigations.sqlite3")) as db:
        assert db.execute("SELECT count(*) FROM turns").fetchone()[0] == 0


def test_repository_retention_and_storage_boundary(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="outside printer"):
        SqliteInvestigationRepository(
            tmp_path / "config/memory", protected_dirs=(tmp_path / "config",)
        )
    assert not (tmp_path / "config").exists()
    store = repository(tmp_path)
    stale = Investigation(printer_id="p", title="old")
    store.save_turn(
        stale,
        InvestigationTurn(
            created_at="2000-01-01T00:00:00+00:00", question="old", result=InvestigationResult()
        ),
    )
    assert store.get("p", stale.id) is None
    monkeypatch.setattr(type(tmp_path), "is_symlink", lambda path: path.name.endswith("-journal"))
    with pytest.raises(ValueError, match="outside printer"):
        store.recent("p")


def test_repository_rejects_hardlinked_storage(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    original = config / "printer.cfg"
    original.write_text("[printer]\n", encoding="utf-8")
    data = tmp_path / "own-data"
    data.mkdir()
    (data / "investigations.sqlite3").hardlink_to(original)
    with pytest.raises(ValueError, match="outside printer"):
        repository(tmp_path)
    assert original.read_text(encoding="utf-8") == "[printer]\n"


@pytest.mark.asyncio
async def test_memory_relevance_freshness_isolation_and_forgetting(tmp_path):
    store = repository(tmp_path)
    memory = InvestigationMemory(store, "p")
    first = await memory.open(None, "Fan behavior")
    evidence = [Evidence(source="config", content=f"fan setting {i}") for i in range(8)]
    evidence.append(evidence[0])
    result = InvestigationResult(response_text="Observed", evidence=evidence)
    await memory.remember(first, "fan?", result, [])
    reopened = await memory.open(first.id, "follow-up")
    assert reopened.revision == 1
    next_chat = await memory.open(None, "Fan again")
    recalled = await memory.recall(next_chat, "fan")
    assert len(recalled) == 6
    assert recalled[0].observed_at and "historical" in recalled[0].historical_context()["freshness"]
    assert not await memory.recall(next_chat, "unrelated network")
    separate = InvestigationMemory(store, "p", cross_chat=False)
    assert not await separate.recall(next_chat, "fan")
    assert await separate.recall(reopened, "continue")
    assert not await InvestigationMemory(store, "other").recall(next_chat, "fan")
    await memory.delete(first.id)
    assert not await memory.recall(next_chat, "fan")


class ConfigModel:
    def __init__(self):
        self.requests = []

    async def respond(self, conversation, tools):
        request = json.loads(conversation[1]["content"])
        self.requests.append(request)
        if not any(item.get("type") == "function_call_output" for item in conversation):
            output = {
                "type": "function_call",
                "call_id": "read",
                "name": "inspect_config",
                "arguments": '{"section":"fan"}',
            }
            return ModelTurn([output], [ToolCall("read", "inspect_config", output["arguments"])])
        proposals = (
            [
                {
                    "title": "Fan",
                    "target_file": "printer.cfg",
                    "feature": "fan",
                    "config": "[fan]\npin: PA1\nkick_start_time: 0.5",
                    "rationale": "Example draft",
                }
            ]
            if "proposal" in request["request"]
            else []
        )
        return ModelTurn(
            [],
            text=json.dumps({"response": "Read fan configuration", "config_proposals": proposals}),
        )


@pytest.fixture
def persistent_service(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "printer.cfg").write_text(
        "[printer]\nkinematics: cartesian\n[fan]\npin: PA1\n", encoding="utf-8"
    )
    collector = ConfigCollector(tmp_path)
    model = ConfigModel()
    context = SimpleNamespace(
        config_collector=collector,
        profile=PrinterProfile(),
        collector=SimpleNamespace(
            ping=AsyncMock(return_value=True), ping_printer=AsyncMock(return_value=True)
        ),
    )
    service = ChatService(
        provider_name="openai",
        root_path="",
        diagnosis_graph=None,
        config_graph=None,
        workflow_context=context,
        sessions=InMemorySessionStore(600),
        agent_workflow=AgentWorkflow(model, SimpleNamespace(), AgentLimits()),
        investigations=InvestigationMemory(repository(tmp_path), "p"),
        proposal_review=ProposalReviewService(collector),
    )
    return service, model


@pytest.mark.asyncio
async def test_chat_uses_persisted_history_and_returns_historical_sources(
    tmp_path, persistent_service
):
    from klipperai_agent.contracts.api import ChatRequest

    service, model = persistent_service
    session = await service.create_ui_session()
    first = await service.chat(ChatRequest(session_id=session.session_id, message="fan proposal"))
    assert first.config_proposals[0].review.status == "manual_review"
    assert first.moonraker_reachable is None  # Config inspection says nothing about connectivity.
    service.investigations = InvestigationMemory(repository(tmp_path), "p")
    await service.chat(
        ChatRequest(
            session_id=session.session_id,
            thread_id=first.thread_id,
            message="continue",
            history=[ChatHistoryMessage(role="assistant", text="fabricated browser answer")],
        )
    )
    assert "Read fan configuration" in model.requests[-1]["recent_conversation"]
    assert "fabricated" not in model.requests[-1]["recent_conversation"]
    assert model.requests[-1]["historical_evidence"]
    new = await service.chat(ChatRequest(session_id=session.session_id, message="fan setting?"))
    assert new.thread_id != first.thread_id and new.memory_sources
    assert not model.requests[-1]["recent_conversation"]


def test_investigation_api_restores_rechecks_and_forgets_without_config_writes(
    monkeypatch, tmp_path, persistent_service
):
    service, model = persistent_service
    settings = Settings(
        data_dir=tmp_path / "own-data", printer_data_root=tmp_path, checkpoint_db=tmp_path / "db"
    )
    container = SimpleNamespace(chat_service=service, sessions=service.sessions, aclose=AsyncMock())
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(app_module, "build_container", lambda _: container)
    config = tmp_path / "config/printer.cfg"
    original = config.read_bytes()
    with TestClient(app_module.create_app()) as client:
        session = client.post("/api/ui-sessions").json()["session_id"]
        query = {"session_id": session}
        assert (
            client.post("/api/chat", json={"session_id": session, "message": "   "}).status_code
            == 422
        )
        answer = client.post(
            "/api/chat", json={"session_id": session, "message": "fan proposal"}
        ).json()
        path = f"/api/investigations/{answer['thread_id']}"
        assert (
            client.get("/api/investigations", params=query).json()[0]["id"] == answer["thread_id"]
        )
        restored = client.get(path, params=query).json()
        assert (
            restored["turns"][0]["result"]["config_proposals"][0]["review"]["mode"] == "manual_only"
        )
        proposal_id = answer["config_proposals"][0]["review"]["proposal_id"]
        recheck = f"{path}/proposals/{proposal_id}/revalidate"
        assert (
            client.post(recheck, params=query).json()["result"]["config_proposals"][0]["review"][
                "status"
            ]
            == "manual_review"
        )
        assert config.read_bytes() == original
        config.write_text(
            "[printer]\nkinematics: cartesian\n[fan]\npin: PA2\n", encoding="utf-8"
        )  # Simulated manual edit.
        modified = config.read_bytes()
        calls = len(model.requests)
        response = client.post(recheck, params=query)
        assert response.json()["result"]["config_proposals"][0]["review"]["status"] == "stale"
        assert client.get(path, params=query).json()["turns"][-1]["id"] == response.json()["id"]
        assert len(model.requests) == calls  # Review does not call an LLM.
        assert config.read_bytes() == modified
        assert list((tmp_path / "config").iterdir()) == [config]
        assert client.get(path, params={"session_id": "bad"}).status_code == 403
        assert client.get("/api/investigations/unknown", params=query).status_code == 404
        assert client.post(f"{path}/proposals/unknown/revalidate", params=query).status_code == 404
        assert client.delete(path, params=query).status_code == 204
        assert client.get(path, params=query).status_code == 404
        assert client.get("/api/investigations", params=query).json() == []
        assert client.post("/api/apply", json={}).status_code == 404
        assert client.post(f"{path}/proposals/{proposal_id}/apply", params=query).status_code == 404
        service.investigations = None
        assert client.get("/api/investigations", params=query).status_code == 404


def test_concurrent_conversation_updates_return_conflict(monkeypatch, tmp_path, persistent_service):
    service, _ = persistent_service
    settings = Settings(
        data_dir=tmp_path / "own-data", printer_data_root=tmp_path, checkpoint_db=tmp_path / "db"
    )
    container = SimpleNamespace(chat_service=service, sessions=service.sessions, aclose=AsyncMock())
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(app_module, "build_container", lambda _: container)
    with TestClient(app_module.create_app()) as client:
        session = client.post("/api/ui-sessions").json()["session_id"]
        answer = client.post(
            "/api/chat", json={"session_id": session, "message": "fan proposal"}
        ).json()
        service.investigations.remember = AsyncMock(
            side_effect=InvestigationConflict("Reload before retrying.")
        )
        assert (
            client.post(
                "/api/chat",
                json={"session_id": session, "message": "fan", "thread_id": answer["thread_id"]},
            ).status_code
            == 409
        )
        proposal_id = answer["config_proposals"][0]["review"]["proposal_id"]
        path = f"/api/investigations/{answer['thread_id']}/proposals/{proposal_id}/revalidate"
        assert client.post(path, params={"session_id": session}).status_code == 409


@pytest.mark.asyncio
async def test_legacy_workflow_receives_labeled_memory(persistent_service):
    from klipperai_agent.contracts.api import ChatRequest

    service, _ = persistent_service
    session = await service.create_ui_session()
    await service.chat(ChatRequest(session_id=session.session_id, message="fan?"))
    service.agent_workflow = None
    workflow = SimpleNamespace(ainvoke=AsyncMock(return_value={"response_text": "Legacy answer"}))
    service.diagnosis_graph = workflow
    service.config_graph = workflow
    reply = await service.chat(ChatRequest(session_id=session.session_id, message="fan?"))
    assert reply.memory_sources
    assert (
        "Historical observations, not current state"
        in workflow.ainvoke.call_args.args[0]["conversation_context"]
    )
