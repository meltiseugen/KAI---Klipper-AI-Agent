import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

import klipperai_agent.providers.json_client as json_client
from klipperai_agent.agent.models import AgentLimits
from klipperai_agent.agent.tools.search import SearchArguments, WebSearchTool
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.application.chat import ChatService
from klipperai_agent.application.knowledge import PrinterKnowledge
from klipperai_agent.application.sessions import InMemorySessionStore
from klipperai_agent.contracts.api import ChatRequest
from klipperai_agent.domain.knowledge import KnowledgeSetup
from klipperai_agent.infrastructure.public_docs import public_target
from klipperai_agent.knowledge.sources import document_source
from klipperai_agent.profile.models import PrinterProfile
from tests.knowledge_helpers import setup
from tests.test_agent import ScriptedModel, answer, call
from tests.test_agent import tool_context as tool_context
from tests.test_knowledge_storage import repository
from tests.test_services import _FakeCollector, _FakeGraph


@pytest.mark.asyncio
async def test_agent_inputs_tools_outputs_and_evidence_redact_credentials(tool_context, tmp_path):
    path = tmp_path / "config/printer.cfg"
    path.write_text("[printer]\nkinematics: corexy\npassword=config-secret\n[fan]\npin: PA1\n")
    tool_context.moonraker.get_printer_info.return_value = {
        "state": "ready",
        "api_key": "moonraker-secret",
    }
    model = ScriptedModel(call("get_printer_status"), answer("password=model-secret"))
    workflow = AgentWorkflow(model, tool_context.moonraker, AgentLimits())
    result = await workflow.ainvoke(
        {
            "user_message": "password=user-secret\nDiagnose the fan",
            "conversation_context": "token=history-secret",
            "artifacts": [
                {"kind": "system_log", "label": "pasted", "content": "api_key=artifact-secret"}
            ],
        },
        context=tool_context.services,
    )
    sent = json.dumps(model.conversations)
    for secret in (
        "config-secret",
        "moonraker-secret",
        "user-secret",
        "history-secret",
        "artifact-secret",
    ):
        assert secret not in sent and secret not in json.dumps(result)
    assert "model-secret" not in json.dumps(result)
    assert "PA1" in sent and result["response_text"] == "password=[REDACTED]"
    assert "config-secret" in path.read_text()


@pytest.mark.asyncio
async def test_redaction_does_not_make_valid_artifacts_exceed_existing_schema(tool_context):
    model = ScriptedModel(answer())
    workflow = AgentWorkflow(model, tool_context.moonraker, AgentLimits())
    result = await workflow.ainvoke(
        {
            "user_message": "Review the log",
            "artifacts": [{"kind": "system_log", "label": "log", "content": "token=x\n" * 5000}],
        },
        context=tool_context.services,
    )
    assert result["agent_status"] == "completed"
    assert "token=x" not in json.dumps(model.conversations)


@pytest.mark.asyncio
async def test_chat_redacts_compatibility_workflows_and_keeps_session_identity():
    graph = _FakeGraph("diagnostics", {"response_text": "token=output-secret"})
    service = ChatService(
        provider_name="openai",
        root_path="",
        diagnosis_graph=graph,
        config_graph=graph,
        workflow_context=SimpleNamespace(
            collector=_FakeCollector(), profile=PrinterProfile(firmware_flavor="Klipper")
        ),
        sessions=InMemorySessionStore(3600),
    )
    session = await service.create_ui_session()
    response = await service.chat(
        ChatRequest(
            session_id=session.session_id,
            message="Why stopped? password=question-secret",
            artifacts=[{"kind": "system_log", "label": "log", "content": "token=artifact-secret"}],
            history=[{"role": "user", "text": "api_key=history-secret"}],
        )
    )
    state = json.dumps(graph.calls[0]["state"])
    for secret in ("question-secret", "artifact-secret", "history-secret"):
        assert secret not in state
    assert response.session_id == session.session_id
    assert response.response == "token=[REDACTED]"


@pytest.mark.asyncio
async def test_legacy_provider_redacts_exact_key_but_keeps_auth_header(monkeypatch):
    sent = []

    async def handle(request):
        sent.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        json_client.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(handle)),
    )
    provider = json_client.OpenAIJsonClient("fake-model", "exact-provider-key")
    assert await provider.complete_json(
        system_prompt="system", user_prompt="exact-provider-key password=prompt-secret"
    ) == {"ok": True}
    assert sent[0].headers["Authorization"] == "Bearer exact-provider-key"
    assert b"exact-provider-key" not in sent[0].content and b"prompt-secret" not in sent[0].content


@pytest.mark.asyncio
async def test_search_and_document_credentials_never_leave_host(tool_context):
    search = SimpleNamespace(search=AsyncMock())
    result = await WebSearchTool(search).execute(
        SearchArguments(query="Klipper api_key=private-key"), tool_context
    )
    assert "credential" in result["error"]
    search.search.assert_not_called()
    component = setup().components[0]
    url = "https://www.klipper3d.org/Config_Reference.html?token=private-key"
    with pytest.raises(ValueError):
        document_source(component, url)
    with pytest.raises(ValueError):
        public_target(url, ["1.1.1.1"])


@pytest.mark.asyncio
async def test_knowledge_facts_redacted_on_save_and_old_data_read(tmp_path):
    store = repository(tmp_path)
    service = PrinterKnowledge(store, SimpleNamespace(), {})
    saved = await service.save(KnowledgeSetup(facts="password=private-fact"))
    assert saved.facts == "password=[REDACTED]" and store.setup().facts == saved.facts
    store.save_setup(saved.copy(update={"facts": "api_key=legacy-fact"}))
    status = await service.status()
    assert "legacy-fact" not in json.dumps(status)
