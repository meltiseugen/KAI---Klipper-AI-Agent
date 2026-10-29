"""Live-check wiring with synthetic transports; these are not live acceptance results."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import klipperai_agent.web.app as app_module
from klipperai_agent.application.hardware_validation import validate_hardware
from klipperai_agent.application.knowledge import PrinterKnowledge
from klipperai_agent.providers.probe import probe_provider
from klipperai_agent.runtime.settings import Settings
from tests.knowledge_helpers import setup, snapshot
from tests.test_agent_integration import agent_service as agent_service
from tests.test_firmware_knowledge import pdf_document, pinned
from tests.test_knowledge_storage import repository


def printer():
    return SimpleNamespace(
        get_printer_info=AsyncMock(
            return_value={"state": "ready", "software_version": "v0.13.0-gaaaaaaa"}
        ),
        list_printer_objects=AsyncMock(
            return_value=["webhooks", "configfile", "extruder", "arbitrary"]
        ),
        query_printer_objects=AsyncMock(
            return_value={
                "configfile": {"settings": {"mcu": {}}, "save_config_pending": False},
                "extruder": {"temperature": 22, "target": 0, "private": "never return"},
            }
        ),
    )


@pytest.mark.asyncio
async def test_live_read_report_has_fixed_fields_and_explicit_verification_limits():
    reader = printer()
    config = SimpleNamespace(collect_with_options=lambda: snapshot())
    report = await validate_hardware(pinned(), reader, config)
    assert report["printer_reachable"] and report["firmware"]["commit_prefix_matches"]
    assert not report["physical_wiring_verified"] and not report["provider_checked"]
    assert "never return" not in json.dumps(report)
    reader.query_printer_objects.assert_awaited_with(
        {"webhooks": None, "configfile": None, "extruder": None}
    )
    assert (await validate_hardware(setup(), None, config))["gaps"]
    reader.get_printer_info.side_effect = ValueError("private")
    assert not (await validate_hardware(setup(), reader, config))["printer_reachable"]
    reader = printer()
    reader.list_printer_objects.return_value = []
    partial = await validate_hardware(setup(), reader, config)
    assert any("Loaded" in gap for gap in partial["gaps"])
    assert any("exact-commit" in gap for gap in partial["gaps"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output,passed", [('{"ok":true}', True), ('{"ok":false}', False), ("not JSON", False)]
)
async def test_provider_probe_sends_no_printer_data_and_uses_a_bounded_schema(output, passed):
    client = SimpleNamespace(
        create=AsyncMock(
            return_value=[{"type": "message", "content": [{"type": "output_text", "text": output}]}]
        )
    )
    report = await probe_provider(client)
    assert report["passed"] == passed and report["printer_data_sent"] is False
    request = client.create.call_args.kwargs
    assert request["max_output_tokens"] == 512 and request["tools"] == []
    assert request["text"]["format"]["strict"]
    assert not (await probe_provider(None))["passed"]


def test_session_protected_inventory_diagram_and_live_check_endpoints(
    monkeypatch, tmp_path, agent_service
):
    store = repository(tmp_path)
    knowledge = PrinterKnowledge(
        store,
        SimpleNamespace(fetch=AsyncMock()),
        {},
        printer=printer(),
        config=SimpleNamespace(collect_with_options=lambda: snapshot()),
    )
    import asyncio

    asyncio.run(knowledge.save(setup()))
    doc = pdf_document()
    store.save_document(doc, b"cached")
    agent_service.knowledge = knowledge
    container = SimpleNamespace(
        sessions=agent_service.sessions,
        chat_service=agent_service,
        aclose=AsyncMock(),
        providers=SimpleNamespace(),
        responses=None,
    )
    monkeypatch.setattr(app_module, "get_settings", lambda: Settings(data_dir=tmp_path / "data"))
    monkeypatch.setattr(app_module, "build_container", lambda _: container)
    with TestClient(app_module.create_app()) as client:
        session = client.post("/api/ui-sessions").json()["session_id"]
        base = "/api/knowledge"
        assert client.post(base + "/validate", json={"session_id": "bad"}).status_code == 403
        observation = dict(
            role="mainboard",
            connector="FAN1",
            occupancy="occupied",
            attached_device="Exhaust",
            confirmed=True,
        )
        saved = client.post(
            base + "/connectors",
            json={"session_id": session, "revision": 1, "observation": observation},
        )
        assert saved.status_code == 200 and saved.json()["connectors"][0]["observed_at"]
        note = dict(
            document_id=doc.id,
            digest=doc.digest,
            page=1,
            text="Upper right connector",
            confirmed=True,
        )
        saved = client.post(
            base + "/diagram-notes",
            json={"session_id": session, "revision": 2, "observation": note},
        )
        assert saved.status_code == 200
        assert (
            client.post(
                base + "/review-buses",
                json={
                    "session_id": session,
                    "role": "mainboard",
                    "signature": "b" * 64,
                    "revision": 3,
                },
            ).status_code
            == 409
        )
        validated = client.post(base + "/validate", json={"session_id": session})
        assert validated.status_code == 200 and validated.json()["printer_reachable"]
        assert client.get(base, params={"session_id": session}).json()["setup"]["validation"][
            "checked_at"
        ]
        assert client.post("/api/providers/probe", json={"session_id": "bad"}).status_code == 403
        probe = client.post("/api/providers/probe", json={"session_id": session})
        assert probe.status_code == 200 and probe.json()["passed"] is False
        assert (
            client.post(
                base + "/connectors",
                json={
                    "session_id": session,
                    "revision": 4,
                    "observation": {**observation, "confirmed": False},
                },
            ).status_code
            == 422
        )
