import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

import klipperai_agent.web.app as app_module
from klipperai_agent.application.knowledge import PrinterKnowledge
from klipperai_agent.domain.knowledge import KnowledgeConflict
from klipperai_agent.runtime.settings import Settings
from tests.knowledge_helpers import documents, researcher
from tests.test_agent_integration import agent_service as agent_service
from tests.test_knowledge_storage import repository


def test_session_protected_refresh_saved_details_downloads_and_restart(
    monkeypatch, tmp_path, agent_service
):
    store = repository(tmp_path)
    knowledge = PrinterKnowledge(
        store,
        SimpleNamespace(fetch=AsyncMock(return_value=(b"reference", "reference", "text"))),
        {"mainboard": "Manta E3EZ"},
        researcher(),
    )
    agent_service.knowledge = knowledge
    settings = Settings(
        data_dir=tmp_path / "data", printer_data_root=tmp_path, root_path="/klipperai"
    )
    container = SimpleNamespace(
        sessions=agent_service.sessions, chat_service=agent_service, aclose=knowledge.aclose
    )
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    monkeypatch.setattr(app_module, "build_container", lambda _: container)
    with TestClient(app_module.create_app()) as client:
        session = client.post("/api/ui-sessions").json()["session_id"]
        params = {"session_id": session}
        base = "/klipperai/api/knowledge"
        assert client.get(base, params={"session_id": "bad"}).status_code == 403
        assert "printer-knowledge" in client.get("/api/bootstrap", params=params).json()["features"]
        page = client.get("/klipperai/").text
        assert "Build printer knowledge" in page and "class PrinterKnowledgePanel" in page
        status = client.get(base, params=params)
        assert status.headers["cache-control"] == "no-store"
        data = status.json()["setup"]
        data["components"][0].update(revision="1.0", mcu="mcu", connection="USB", confirmed=True)
        saved = client.put(base + "/details", json={**params, "setup": data})
        assert saved.status_code == 200 and saved.json()["revision"] == 1
        assert client.put(base + "/details", json={**params, "setup": data}).status_code == 409
        assert (
            client.put(
                base + "/details", json={**params, "setup": {"shell": "restart"}}
            ).status_code
            == 422
        )
        assert (
            client.post(base + "/refresh", json={**params, "url": "http://localhost"}).status_code
            == 422
        )
        assert client.post(base + "/refresh", json=params).status_code == 202
        client.portal.call(lambda: knowledge._task)
        assert client.get(base, params=params).json()["job"]["state"] == "completed"
        document_id = client.get(base, params=params).json()["documents"][0]["id"]
        download = client.get(base + "/documents/" + document_id, params=params)
        assert (
            download.content == b"reference"
            and download.headers["x-content-type-options"] == "nosniff"
        )
        assert (
            download.headers["content-disposition"] == f'attachment; filename="{document_id}.txt"'
        )
        assert client.get(base + "/documents/unknown", params=params).status_code == 404
        assert client.get(base + "/documents/eddy-guide", params=params).status_code == 404
        doc = next(doc for doc in documents() if doc.id == "eddy-guide")
        store.save_document(doc, b"cached")
        restarted = PrinterKnowledge(
            repository(tmp_path), SimpleNamespace(), {"mainboard": "Manta E3EZ"}
        )
        agent_service.knowledge = restarted
        assert client.get(base, params=params).json()["setup"]["components"][0]["confirmed"]
        assert client.get(base + "/documents/eddy-guide", params=params).status_code == 404
        assert client.get(base + "/documents/" + "f" * 32, params=params).status_code == 404
        assert client.get(base + "/documents/" + document_id, params=params).content == b"reference"
        doc = store.documents()[0]
        doc.content = "FAN0 pin PA8"
        from klipperai_agent.domain.knowledge import FanMapping

        doc.fan_mappings = [FanMapping(connector="FAN0", pin="PA8", quote=doc.content)]
        store.save_document(doc, b"reference")
        evidence = client.get(base, params=params).json()["components"][0]["fan_evidence"]
        review = {**params, "role": "mainboard", "signature": evidence["signature"], "revision": 1}
        assert client.post(base + "/review-mappings", json=review).status_code == 200
        assert client.post(base + "/review-mappings", json=review).status_code == 409
        monkeypatch.setattr(
            restarted,
            "status",
            AsyncMock(side_effect=sqlite3.OperationalError("private storage path")),
        )
        failed = client.get(base, params=params)
        assert failed.status_code == 503 and "private storage path" not in failed.text
        monkeypatch.setattr(
            restarted, "save", AsyncMock(side_effect=KnowledgeConflict("Refresh still running"))
        )
        assert (
            client.put(base + "/details", json={**params, "setup": saved.json()}).status_code == 409
        )
        agent_service.knowledge = None
        assert client.get(base, params=params).status_code == 404
        assert not (tmp_path / "config").exists()
