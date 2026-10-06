from __future__ import annotations

from types import SimpleNamespace

import pytest

import klipperai_agent.application.request_context as services_module
from klipperai_agent.application.chat import (
    ChatService,
)
from klipperai_agent.application.request_context import _infer_inline_question_artifact
from klipperai_agent.application.sessions import InMemorySessionStore
from klipperai_agent.contracts.api import ChatHistoryMessage, ChatRequest
from klipperai_agent.profile.models import PrinterProfile


class _FakeGraph:
    def __init__(self, name: str, result: dict[str, object]) -> None:
        self.name = name
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def ainvoke(self, state: dict[str, object], **kwargs: object) -> dict[str, object]:
        self.calls.append({"state": state, **kwargs})
        return self.result


class _FakeCollector:
    async def ping(self) -> bool:
        return True

    async def ping_printer(self) -> bool:
        return True


class _FakeIntentRouter:
    name = "fake"

    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.calls: list[str] = []

    async def classify(self, message: str) -> dict[str, object]:
        self.calls.append(message)
        return self.result


@pytest.mark.asyncio
async def test_chat_service_routes_config_request_to_config_graph() -> None:
    sessions = InMemorySessionStore(ttl_seconds=60)
    session = sessions.create()

    diagnosis_graph = _FakeGraph("diagnostics", {"response_text": "diagnostics"})
    config_graph = _FakeGraph(
        "config",
        {
            "response_text": "config",
            "config_proposals": [
                {
                    "feature": "fan",
                    "title": "Fan config",
                    "target_file": "klipperai/fan.cfg",
                    "config": "[fan]\npin: PA1\n",
                    "rationale": "test",
                    "assumptions": [],
                    "warnings": [],
                }
            ],
        },
    )
    service = ChatService(
        provider_name="stub",
        root_path="",
        diagnosis_graph=diagnosis_graph,
        config_graph=config_graph,
        workflow_context=SimpleNamespace(
            collector=_FakeCollector(),
            profile=PrinterProfile(firmware_flavor="Kalico"),
        ),
        sessions=sessions,
    )

    response = await service.chat(
        ChatRequest(
            session_id=session.session_id,
            message="Generate me a config for a fan",
            artifacts=[],
        )
    )

    assert response.response == "config"
    assert len(response.config_proposals) == 1
    assert not diagnosis_graph.calls
    assert config_graph.calls
    assert config_graph.calls[0]["state"]["chat_intent"]["intent"] == "generate_config"
    assert config_graph.calls[0]["state"]["chat_intent"]["needs_logs"] is False


@pytest.mark.asyncio
async def test_chat_service_routes_config_lookup_request_to_config_graph() -> None:
    sessions = InMemorySessionStore(ttl_seconds=60)
    session = sessions.create()

    diagnosis_graph = _FakeGraph("diagnostics", {"response_text": "diagnostics"})
    config_graph = _FakeGraph(
        "config",
        {
            "response_text": "I found 1 active [extruder] section in the current config tree.",
            "config_proposals": [],
            "source_citations": [
                {
                    "label": "printer.cfg:10 [extruder]",
                    "path": "printer.cfg",
                    "line_number": 10,
                    "section": "extruder",
                    "excerpt": "[extruder]\nstep_pin: PA1\n",
                }
            ],
        },
    )
    service = ChatService(
        provider_name="stub",
        root_path="",
        diagnosis_graph=diagnosis_graph,
        config_graph=config_graph,
        workflow_context=SimpleNamespace(
            collector=_FakeCollector(),
            profile=PrinterProfile(firmware_flavor="Kalico"),
        ),
        sessions=sessions,
    )

    response = await service.chat(
        ChatRequest(
            session_id=session.session_id,
            message="Where do I have the extruder defined?",
            artifacts=[],
        )
    )

    assert "extruder" in response.response
    assert len(response.source_citations) == 1
    assert response.source_citations[0].path == "printer.cfg"
    assert "[extruder]" in response.source_citations[0].excerpt
    assert not diagnosis_graph.calls
    assert config_graph.calls
    assert config_graph.calls[0]["state"]["chat_intent"]["intent"] == "config_lookup"


@pytest.mark.asyncio
async def test_chat_service_routes_macro_name_correction_to_config_graph() -> None:
    sessions = InMemorySessionStore(ttl_seconds=60)
    session = sessions.create()

    diagnosis_graph = _FakeGraph("diagnostics", {"response_text": "diagnostics"})
    config_graph = _FakeGraph(
        "config", {"response_text": "SFS_ENABLE is defined in filament.cfg:1."}
    )
    service = ChatService(
        provider_name="stub",
        root_path="",
        diagnosis_graph=diagnosis_graph,
        config_graph=config_graph,
        workflow_context=SimpleNamespace(
            collector=_FakeCollector(),
            profile=PrinterProfile(firmware_flavor="Kalico"),
        ),
        sessions=sessions,
    )

    response = await service.chat(
        ChatRequest(
            session_id=session.session_id,
            message="I mean SFS_ENABLE",
            artifacts=[],
        )
    )

    assert "SFS_ENABLE" in response.response
    assert not diagnosis_graph.calls
    assert config_graph.calls
    assert config_graph.calls[0]["state"]["chat_intent"]["intent"] == "config_lookup"


@pytest.mark.asyncio
async def test_chat_service_routes_problem_language_to_diagnostics_with_logs_enabled() -> None:
    sessions = InMemorySessionStore(ttl_seconds=60)
    session = sessions.create()

    diagnosis_graph = _FakeGraph("diagnostics", {"response_text": "diagnostics"})
    config_graph = _FakeGraph("config", {"response_text": "config"})
    service = ChatService(
        provider_name="stub",
        root_path="",
        diagnosis_graph=diagnosis_graph,
        config_graph=config_graph,
        workflow_context=SimpleNamespace(
            collector=_FakeCollector(),
            profile=PrinterProfile(firmware_flavor="Kalico"),
        ),
        sessions=sessions,
    )

    await service.chat(
        ChatRequest(
            session_id=session.session_id,
            message="Why is SFS_ENABLE failing?",
            artifacts=[],
        )
    )

    assert diagnosis_graph.calls
    assert not config_graph.calls
    assert diagnosis_graph.calls[0]["state"]["chat_intent"]["intent"] == "diagnose_issue"
    assert diagnosis_graph.calls[0]["state"]["chat_intent"]["needs_logs"] is True


@pytest.mark.asyncio
async def test_chat_service_uses_llm_intent_router_for_ambiguous_requests() -> None:
    sessions = InMemorySessionStore(ttl_seconds=60)
    session = sessions.create()

    intent_router = _FakeIntentRouter(
        {
            "intent": "config_explain",
            "target": "SFS_ENABLE",
            "target_section": "gcode_macro SFS_ENABLE",
            "needs_logs": False,
            "confidence": 0.91,
            "rationale": "The user asked to understand a macro.",
        }
    )
    diagnosis_graph = _FakeGraph("diagnostics", {"response_text": "diagnostics"})
    config_graph = _FakeGraph("config", {"response_text": "config"})
    service = ChatService(
        provider_name="stub",
        root_path="",
        diagnosis_graph=diagnosis_graph,
        config_graph=config_graph,
        workflow_context=SimpleNamespace(
            collector=_FakeCollector(),
            intent_router=intent_router,
            profile=PrinterProfile(firmware_flavor="Kalico"),
        ),
        sessions=sessions,
    )

    await service.chat(
        ChatRequest(
            session_id=session.session_id,
            message="Can you help me with SFS_ENABLE?",
            artifacts=[],
        )
    )

    assert intent_router.calls == ["Can you help me with SFS_ENABLE?"]
    assert not diagnosis_graph.calls
    assert config_graph.calls
    assert config_graph.calls[0]["state"]["chat_intent"]["intent"] == "config_explain"


@pytest.mark.asyncio
async def test_chat_service_sends_recent_history_to_intent_router_for_followups() -> None:
    sessions = InMemorySessionStore(ttl_seconds=60)
    session = sessions.create()

    intent_router = _FakeIntentRouter(
        {
            "intent": "config_explain",
            "target": "SFS_ENABLE",
            "target_section": "gcode_macro SFS_ENABLE",
            "needs_logs": False,
            "confidence": 0.94,
            "rationale": "The user is asking whether the previously discussed macro is used in START_PRINT.",
        }
    )
    diagnosis_graph = _FakeGraph("diagnostics", {"response_text": "diagnostics"})
    config_graph = _FakeGraph("config", {"response_text": "config"})
    service = ChatService(
        provider_name="stub",
        root_path="",
        diagnosis_graph=diagnosis_graph,
        config_graph=config_graph,
        workflow_context=SimpleNamespace(
            collector=_FakeCollector(),
            intent_router=intent_router,
            profile=PrinterProfile(firmware_flavor="Kalico"),
        ),
        sessions=sessions,
    )

    await service.chat(
        ChatRequest(
            session_id=session.session_id,
            message="is it used in START_PRINT?",
            history=[
                {"role": "user", "text": "what does SFS_ENABLE macro do?"},
                {
                    "role": "assistant",
                    "text": "SFS_ENABLE enables both filament sensors. It is used by START_PRINT.",
                },
            ],
            artifacts=[],
        )
    )

    assert len(intent_router.calls) == 1
    assert "Recent conversation:" in intent_router.calls[0]
    assert "SFS_ENABLE" in intent_router.calls[0]
    assert "Current user message:\nis it used in START_PRINT?" in intent_router.calls[0]
    assert not diagnosis_graph.calls
    assert config_graph.calls
    state = config_graph.calls[0]["state"]
    assert state["chat_intent"]["intent"] == "config_explain"
    assert "SFS_ENABLE enables both filament sensors" in state["conversation_context"]


@pytest.mark.asyncio
async def test_chat_service_limits_history_by_configured_pairs() -> None:
    sessions = InMemorySessionStore(ttl_seconds=60)
    session = sessions.create()

    intent_router = _FakeIntentRouter(
        {
            "intent": "config_explain",
            "needs_logs": False,
            "confidence": 0.9,
            "rationale": "Follow-up config question.",
        }
    )
    diagnosis_graph = _FakeGraph("diagnostics", {"response_text": "diagnostics"})
    config_graph = _FakeGraph("config", {"response_text": "config"})
    service = ChatService(
        provider_name="stub",
        root_path="",
        diagnosis_graph=diagnosis_graph,
        config_graph=config_graph,
        workflow_context=SimpleNamespace(
            collector=_FakeCollector(),
            intent_router=intent_router,
            profile=PrinterProfile(firmware_flavor="Kalico"),
        ),
        sessions=sessions,
        conversation_history_pairs=1,
    )

    await service.chat(
        ChatRequest(
            session_id=session.session_id,
            message="is it used there?",
            history=[
                {"role": "user", "text": "old user turn"},
                {"role": "assistant", "text": "old assistant turn"},
                {"role": "user", "text": "what does SFS_ENABLE do?"},
                {"role": "assistant", "text": "SFS_ENABLE enables both filament sensors."},
            ],
            artifacts=[],
        )
    )

    context = config_graph.calls[0]["state"]["conversation_context"]
    assert "old user turn" not in context
    assert "old assistant turn" not in context
    assert "what does SFS_ENABLE do?" in context
    assert "SFS_ENABLE enables both filament sensors." in context


@pytest.mark.asyncio
async def test_chat_service_prefers_intent_router_over_deterministic_guess() -> None:
    sessions = InMemorySessionStore(ttl_seconds=60)
    session = sessions.create()

    intent_router = _FakeIntentRouter(
        {
            "intent": "diagnose_issue",
            "target": "extruder",
            "needs_logs": True,
            "confidence": 0.92,
            "rationale": "The user is asking about a failure.",
        }
    )
    diagnosis_graph = _FakeGraph("diagnostics", {"response_text": "diagnostics"})
    config_graph = _FakeGraph("config", {"response_text": "config"})
    service = ChatService(
        provider_name="stub",
        root_path="",
        diagnosis_graph=diagnosis_graph,
        config_graph=config_graph,
        workflow_context=SimpleNamespace(
            collector=_FakeCollector(),
            intent_router=intent_router,
            profile=PrinterProfile(firmware_flavor="Kalico"),
        ),
        sessions=sessions,
    )

    await service.chat(
        ChatRequest(
            session_id=session.session_id,
            message="Where do I have the extruder defined?",
            artifacts=[],
        )
    )

    assert intent_router.calls == ["Where do I have the extruder defined?"]
    assert diagnosis_graph.calls
    assert not config_graph.calls


@pytest.mark.asyncio
async def test_chat_service_promotes_structured_question_text_into_artifact() -> None:
    sessions = InMemorySessionStore(ttl_seconds=60)
    session = sessions.create()

    diagnosis_graph = _FakeGraph("diagnostics", {"response_text": "diagnostics"})
    service = ChatService(
        provider_name="stub",
        root_path="",
        diagnosis_graph=diagnosis_graph,
        config_graph=_FakeGraph("config", {"response_text": "config"}),
        workflow_context=SimpleNamespace(
            collector=_FakeCollector(),
            profile=PrinterProfile(firmware_flavor="Kalico"),
        ),
        sessions=sessions,
    )

    await service.chat(
        ChatRequest(
            session_id=session.session_id,
            message=(
                "Why is Klipper shut down?\n\n"
                "Start printer at Wed May 21 10:00:00 2026\n"
                "MCU 'mcu' shutdown: Timer too close\n"
                "Once the underlying issue is corrected, use the\n"
                '  "FIRMWARE_RESTART" command to reset the firmware.\n'
            ),
            artifacts=[],
        )
    )

    state = diagnosis_graph.calls[0]["state"]
    artifacts = state["artifacts"]
    assert len(artifacts) == 1
    assert artifacts[0]["kind"] == "system_log"
    assert artifacts[0]["label"] == "question-context"


@pytest.mark.asyncio
async def test_bootstrap_includes_printer_profile_summary() -> None:
    sessions = InMemorySessionStore(ttl_seconds=60)
    session = sessions.create()
    service = ChatService(
        provider_name="stub",
        provider_model="stub-model",
        root_path="",
        diagnosis_graph=_FakeGraph("diagnostics", {}),
        config_graph=_FakeGraph("config", {}),
        workflow_context=SimpleNamespace(
            collector=_FakeCollector(),
            profile=PrinterProfile(firmware_flavor="Kalico"),
        ),
        sessions=sessions,
    )

    response = await service.bootstrap(session.session_id)

    assert response.moonraker_reachable is True
    assert response.klipper_reachable is True
    assert response.provider_model == "stub-model"
    assert response.conversation_history_pairs == 10
    assert response.printer_profile is not None
    assert response.printer_profile.firmware_flavor == "Kalico"
    assert "read-only-mode" in response.features


def _service(sessions, diagnosis_graph=None, root_path="") -> ChatService:
    return ChatService(
        provider_name="stub",
        root_path=root_path,
        diagnosis_graph=diagnosis_graph or _FakeGraph("diagnostics", {}),
        config_graph=_FakeGraph("config", {}),
        workflow_context=SimpleNamespace(
            collector=_FakeCollector(),
            profile=PrinterProfile(firmware_flavor="Kalico"),
        ),
        sessions=sessions,
    )


@pytest.mark.asyncio
async def test_create_ui_session_and_invalid_session_errors() -> None:
    sessions = InMemorySessionStore(ttl_seconds=60)
    service = _service(sessions, root_path="/klippyai")
    created = await service.create_ui_session()
    assert created.embed_path == f"/klippyai/embed?session={created.session_id}"

    with pytest.raises(ValueError, match="Invalid or expired"):
        await service.bootstrap("missing")
    with pytest.raises(ValueError, match="Invalid or expired"):
        await service.chat(ChatRequest(session_id="missing", message="help"))


@pytest.mark.asyncio
async def test_diagnostics_chat_maps_all_output_and_preserves_thread() -> None:
    sessions = InMemorySessionStore(ttl_seconds=60)
    session = sessions.create()
    graph = _FakeGraph(
        "diagnostics",
        {
            "response_text": "diagnosed",
            "findings": [
                {
                    "code": "x",
                    "severity": "low",
                    "source": "log",
                    "summary": "summary",
                    "evidence": "evidence",
                    "proposed_fix": "fix",
                }
            ],
            "next_actions": ["act"],
            "patch_proposals": [
                {"target_file": "printer.cfg", "summary": "s", "diff": "d", "rationale": "r"}
            ],
            "moonraker_reachable": True,
        },
    )
    response = await _service(sessions, graph).chat(
        ChatRequest(session_id=session.session_id, thread_id="known", message="Why did it stop?")
    )
    assert response.thread_id == "known"
    assert response.findings[0].code == "x"
    assert response.patch_proposals[0].target_file == "printer.cfg"
    assert graph.calls[0]["config"]["configurable"]["thread_id"] == "diagnostics:known"


@pytest.mark.asyncio
async def test_chat_propagates_graph_errors() -> None:
    class FailingGraph:
        async def ainvoke(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    sessions = InMemorySessionStore(ttl_seconds=60)
    session = sessions.create()
    with pytest.raises(RuntimeError, match="boom"):
        await _service(sessions, FailingGraph()).chat(
            ChatRequest(session_id=session.session_id, message="diagnose this")
        )


def test_inline_artifact_ignores_blank_message() -> None:
    assert _infer_inline_question_artifact("   ", "diagnostics") is None


@pytest.mark.asyncio
async def test_intent_router_failure_and_zero_confidence_fall_back() -> None:
    class FailingRouter:
        async def classify(self, _message):
            raise RuntimeError("offline")

    class UncertainRouter:
        async def classify(self, _message):
            return {"intent": "config_explain", "confidence": 0}

    sessions = InMemorySessionStore(ttl_seconds=60)
    failing = _service(sessions)
    failing.workflow_context.intent_router = FailingRouter()
    assert (await failing._classify_chat_intent("plain question")).intent == "general"

    uncertain = _service(sessions)
    uncertain.workflow_context.intent_router = UncertainRouter()
    assert (await uncertain._classify_chat_intent("plain question")).intent == "general"


def test_history_and_inline_artifact_edge_cases() -> None:
    assert services_module._format_conversation_context([], max_pairs=0) == ""
    history = [
        ChatHistoryMessage(role="user", text="x" * 5000),
        ChatHistoryMessage(role="assistant", text="answer"),
    ]
    context = services_module._format_conversation_context(history, max_pairs=1)
    assert "...[truncated]..." in context
    assert "KlipperAI: answer" in context
    blank = ChatHistoryMessage.construct(role="user", text=" ")
    assert services_module._format_conversation_context([blank], max_pairs=1) == ""

    assert services_module._build_contextual_classification_message("hello", "") == "hello"
    artifacts = services_module._build_chat_artifacts(
        "[fan]\npin: PA1",
        "config",
        [],
    )
    assert artifacts[0].kind == "config_snippet"
    notes = services_module._infer_inline_question_artifact("\n".join(["line"] * 8), "config")
    assert notes is not None and notes.kind == "notes"
