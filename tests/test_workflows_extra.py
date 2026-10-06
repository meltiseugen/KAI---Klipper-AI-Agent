from __future__ import annotations

from types import SimpleNamespace

import pytest

import klipperai_agent.workflows.citations as workflows_citations
import klipperai_agent.workflows.configuration as workflows_configuration
import klipperai_agent.workflows.diagnosis as workflows_diagnosis
import klipperai_agent.workflows.engine as workflows_engine
import klipperai_agent.workflows.text as workflows_text
from klipperai_agent.config.models import (
    ConfigDocument,
    ConfigSectionLocation,
    ConfigSnapshot,
)
from klipperai_agent.contracts.api import ArtifactInput, ConfigProposal, IssueFinding
from klipperai_agent.diagnostics.models import DiagnosticsSnapshot
from klipperai_agent.profile.models import PrinterProfile
from klipperai_agent.providers.models import ConfigAssistantOutput, DiagnosisLLMOutput


def _runtime(**overrides):
    context = dict(
        collector=None,
        rules=None,
        llm=None,
        config_collector=None,
        config_llm=None,
        host_logs=None,
        intent_router=None,
        profile=PrinterProfile(),
    )
    context.update(overrides)
    return SimpleNamespace(context=SimpleNamespace(**context))


@pytest.mark.asyncio
async def test_diagnosis_workflow_nodes_collect_rule_and_call_llm() -> None:
    artifact = ArtifactInput(kind="klippy_log", label="klippy.log", content="Timer too close")
    config_snapshot = ConfigSnapshot(
        root_file="printer.cfg",
        documents=[ConfigDocument("printer.cfg", "[printer]", ["printer"])],
    )

    class Collector:
        async def collect(self, artifacts, **kwargs):
            assert artifacts[0].label == "input"
            assert kwargs == {"include_host_logs": True, "include_host_system": True}
            return DiagnosticsSnapshot(True, {"state": "ready"}, [*artifacts, artifact], ["note"])

    class ConfigCollector:
        def collect(self):
            return config_snapshot

    class Rules:
        def analyze(self, artifacts, *, config_snapshot):
            assert artifacts[-1].label == "klippy.log"
            assert config_snapshot.root_file == "printer.cfg"
            return [
                IssueFinding(
                    code="timer",
                    severity="high",
                    source="klippy.log",
                    summary="timing",
                    evidence="evidence",
                    proposed_fix="fix",
                )
            ]

    class LLM:
        async def analyze(self, payload):
            assert payload.findings[0].code == "timer"
            return DiagnosisLLMOutput(summary="diagnosed", recommended_actions=["fix"])

    runtime = _runtime(
        collector=Collector(), config_collector=ConfigCollector(), rules=Rules(), llm=LLM()
    )
    state = {
        "user_message": "help",
        "artifacts": [{"kind": "notes", "label": "input", "content": "details"}],
    }
    collected = await workflows_diagnosis.collect_context(state, runtime)
    ruled = await workflows_diagnosis.run_rules({**state, **collected}, runtime)
    called = await workflows_diagnosis.call_llm({**state, **collected, **ruled}, runtime)
    assert called["llm_output"]["summary"] == "diagnosed"


def test_compose_response_fallback_branches() -> None:
    likely = workflows_diagnosis.compose_response(
        {
            "llm_output": {
                "summary": "Summary",
                "likely_causes": ["Cause"],
                "recommended_actions": [],
            }
        }
    )
    assert "Most likely: Cause" in likely["response_text"]

    question = workflows_diagnosis.compose_response(
        {"llm_output": {"summary": "Blocked", "follow_up_questions": ["Need logs?"]}}
    )
    assert "Need:" in question["response_text"]

    fallback = workflows_diagnosis.compose_response(
        {
            "findings": [
                {"source": "Summary already names source", "proposed_fix": "Fallback fix"}
            ],
            "llm_output": {"summary": "Summary already names source", "recommended_actions": []},
        }
    )
    assert fallback["next_actions"] == ["Fallback fix"]


def test_config_target_lookup_routing_and_response_fallbacks() -> None:
    target = workflows_configuration.detect_config_target({"user_message": "Generate a fan config"})
    assert target["feature_target"]["feature"] == "fan"
    assert (
        workflows_configuration.resolve_config_lookup({"feature_target": {"intent": "generate"}})
        == {}
    )
    assert workflows_configuration.route_config_request({"response_text": "done"}) == "lookup_done"
    assert workflows_configuration.route_config_request({}) == "call_llm"

    follow_up = workflows_configuration.compose_config_response(
        {"config_output": {"summary": "No proposal", "follow_up_questions": ["Which pin?"]}}
    )
    assert "Need:" in follow_up["response_text"]
    assert follow_up["config_proposals"] == []


@pytest.mark.asyncio
async def test_collect_config_context_without_logs_and_call_config_llm() -> None:
    snapshot = ConfigSnapshot(root_file=None, documents=[])

    class ConfigCollector:
        def collect_with_options(self, **kwargs):
            assert kwargs == {"include_unincluded_configs": False}
            return snapshot

    class ConfigLLM:
        async def propose(self, payload):
            assert payload.target.feature == "fan"
            assert payload.runtime_snapshot.artifacts[0].label == "input"
            return ConfigAssistantOutput(
                summary="generated",
                proposals=[
                    ConfigProposal(
                        feature="fan",
                        title="Fan",
                        target_file="fan.cfg",
                        config="[fan]",
                        rationale="test",
                    )
                ],
            )

    runtime = _runtime(config_collector=ConfigCollector(), config_llm=ConfigLLM())
    state = {
        "user_message": "Generate a fan config",
        "artifacts": [{"kind": "notes", "label": "input", "content": "context"}],
    }
    collected = await workflows_configuration.collect_config_context(state, runtime)
    assert collected["runtime_snapshot"]["notes"] == []
    target = workflows_configuration.detect_config_target(state)
    output = await workflows_configuration.call_config_llm(
        {**state, **target, **collected}, runtime
    )
    assert output["config_output"]["summary"] == "generated"

    completed = await workflows_engine.build_config_graph().ainvoke(state, context=runtime.context)
    assert completed["response_text"].startswith("generated")


def test_helpers_and_graph_builders(monkeypatch) -> None:
    assert workflows_text._dedupe_items("invalid", limit=2) == []
    assert workflows_text._dedupe_items(["", " One ", "one", "Two", "Three"], limit=2) == [
        "One",
        "Two",
    ]

    assert workflows_engine.build_diagnosis_graph() is not None
    assert workflows_engine.build_config_graph() is not None


@pytest.mark.asyncio
async def test_simple_workflow_and_config_target_intent_edges() -> None:
    result = await workflows_engine.SimpleWorkflow(
        [lambda state: {"observed": state["value"]}]
    ).ainvoke(
        {"value": "fan"},
        context=SimpleNamespace(),
    )
    assert result["observed"] == "fan"

    async def async_node(_state):
        return {"async": True}

    async_result = await workflows_engine.SimpleWorkflow([async_node]).ainvoke(
        {},
        context=SimpleNamespace(),
    )
    assert async_result["async"] is True

    empty = workflows_configuration._config_target_from_chat_intent(
        {"chat_intent": {"intent": "config_lookup", "rationale": "follow-up"}}
    )
    assert empty is not None and empty.feature == "generic"

    section = workflows_configuration._config_target_from_chat_intent(
        {"chat_intent": {"intent": "config_lookup", "target_section": "[fan]"}}
    )
    assert section is not None and section.section_name == "fan"

    explained = workflows_configuration._config_target_from_chat_intent(
        {"chat_intent": {"intent": "config_explain", "target": "SFS_ENABLE"}}
    )
    assert explained is not None and explained.intent == "explain"

    edited = workflows_configuration._config_target_from_chat_intent(
        {"chat_intent": {"intent": "edit_existing_config", "target": "fan"}}
    )
    assert edited is not None and edited.intent == "edit"

    located = workflows_configuration._config_target_from_chat_intent(
        {"chat_intent": {"intent": "config_lookup", "target": "fan"}}
    )
    assert located is not None and located.intent == "locate"


def test_config_citation_helper_edge_paths() -> None:
    snapshot = ConfigSnapshot(
        root_file="printer.cfg",
        documents=[
            ConfigDocument(
                "printer.cfg",
                "[fan]\npin: PA1\n[gcode_macro TEST]\ngcode:\n  G28",
                ["fan", "gcode_macro TEST"],
            )
        ],
        section_locations=[
            ConfigSectionLocation("printer.cfg", 1, "fan"),
            ConfigSectionLocation("printer.cfg", 3, "gcode_macro TEST"),
        ],
    )
    base = {"user_message": "plain", "config_snapshot": snapshot.to_state()}
    assert workflows_citations._config_source_target_from_state(base) is None
    assert workflows_citations._find_exact_source_locations(snapshot, "", limit=1) == []
    assert workflows_citations._looks_like_config_section_reference("file.cfg") is False
    assert (
        workflows_citations._format_source_citation_label("printer.cfg", 0, "fan")
        == "printer.cfg [fan]"
    )
    assert workflows_citations._truncate_source_excerpt("x" * 12001).endswith("...[truncated]...")

    fan = workflows_citations._build_config_source_citations(
        base, response_text="See [fan].", limit=1
    )
    assert fan[0]["section"] == "fan"
    macro = workflows_citations._build_config_source_citations(
        base, response_text="Run TEST.", limit=1
    )
    assert macro[0]["section"] == "gcode_macro TEST"
