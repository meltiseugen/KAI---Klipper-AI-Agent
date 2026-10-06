from __future__ import annotations

import pytest
from pydantic import SecretStr

import klipperai_agent.providers.config_stub as providers_config_stub
import klipperai_agent.providers.factory as providers_factory
import klipperai_agent.providers.json_client as providers_json_client
import klipperai_agent.providers.models as providers_models
import klipperai_agent.providers.normalization as providers_normalization
import klipperai_agent.providers.openai as providers_openai
import klipperai_agent.providers.stub as providers_stub
from klipperai_agent.config.models import (
    ConfigDocument,
    ConfigRequestTarget,
    ConfigSnapshot,
)
from klipperai_agent.config.requests import ConfigPromptPayload
from klipperai_agent.contracts.api import IssueFinding
from klipperai_agent.diagnostics.models import DiagnosticsSnapshot
from klipperai_agent.diagnostics.requests import DiagnosisPromptPayload
from klipperai_agent.profile.models import PrinterProfile
from klipperai_agent.runtime.settings import Settings


def _snapshot_with(*sections: str) -> ConfigSnapshot:
    content = "\n".join(f"[{section}]\nvalue: 1" for section in sections)
    return ConfigSnapshot(
        root_file="printer.cfg",
        documents=[ConfigDocument(path="printer.cfg", content=content, sections=list(sections))],
        notes=[],
    )


@pytest.mark.asyncio
async def test_stub_diagnosis_with_and_without_findings() -> None:
    finding = IssueFinding(
        code="timer",
        severity="high",
        source="klippy.log",
        summary="Timer issue",
        evidence="Timer too close",
        proposed_fix="Reduce load",
    )
    base = dict(
        user_message="help",
        snapshot=DiagnosticsSnapshot(True, {}, []),
        config_snapshot=ConfigSnapshot(root_file=None, documents=[], notes=[]),
    )
    provider = providers_stub.StubDiagnosisProvider()
    matched = await provider.analyze(
        DiagnosisPromptPayload(
            **base, findings=[finding], profile=PrinterProfile(firmware_flavor="Kalico")
        )
    )
    assert matched.summary.startswith("Timer issue")
    assert matched.recommended_actions == ["Reduce load"]

    unmatched = await provider.analyze(
        DiagnosisPromptPayload(
            **base, findings=[], profile=PrinterProfile(firmware_flavor="Klipper")
        )
    )
    assert "No deterministic" in unmatched.summary
    assert "Klipper" in unmatched.summary


@pytest.mark.asyncio
async def test_stub_config_profile_specific_warnings() -> None:
    provider = providers_config_stub.StubConfigAssistantProvider()
    snapshot = _snapshot_with("fan", "klippyai managed")

    async def propose(feature: str, profile: PrinterProfile):
        return await provider.propose(
            ConfigPromptPayload(
                user_message="configure",
                snapshot=snapshot,
                target=ConfigRequestTarget(feature=feature, rationale="test"),
                profile=profile,
            )
        )

    fan = await propose("fan", PrinterProfile(canbus_interfaces=["can0"]))
    assert any("fan-related" in warning for warning in fan.proposals[0].warnings)
    assert any("CAN-connected" in warning for warning in fan.proposals[0].warnings)
    assert "Detected printer profile" in fan.summary

    probe = await propose("probe", PrinterProfile(probe_type="beacon"))
    assert any("beacon" in warning for warning in probe.proposals[0].warnings)

    motion = await propose("filament", PrinterProfile(filament_sensor="motion"))
    assert any("motion-style" in warning for warning in motion.proposals[0].warnings)
    switch = await propose("filament", PrinterProfile(filament_sensor="switch"))
    assert any("switch-style" in warning for warning in switch.proposals[0].warnings)
    none = await propose("filament", PrinterProfile(filament_sensor="none"))
    assert any("no filament sensor" in item for item in none.proposals[0].assumptions)


@pytest.mark.asyncio
async def test_openai_providers_build_prompts_and_normalize_results() -> None:
    class Client:
        def __init__(self, result):
            self.result = result
            self.calls = []

        async def complete_json(self, **kwargs):
            self.calls.append(kwargs)
            return self.result

    provider = providers_openai.OpenAIDiagnosisProvider("model-a", "secret")
    diagnosis_client = Client({"recommended_actions": "restart"})
    provider._client = diagnosis_client
    payload = DiagnosisPromptPayload(
        user_message="help",
        snapshot=DiagnosticsSnapshot(False, None, []),
        config_snapshot=ConfigSnapshot(root_file=None, documents=[], notes=[]),
        findings=[],
        profile=PrinterProfile(),
    )
    diagnosis_result = await provider.analyze(payload)
    assert diagnosis_result.summary == "No diagnosis was returned."
    assert "No deterministic findings." in diagnosis_client.calls[0]["user_prompt"]

    intent_provider = providers_openai.OpenAIIntentRouterProvider("model-i", "secret")
    intent_provider._client = Client(
        {
            "intent": "general",
            "target": "",
            "target_section": "",
            "needs_logs": False,
            "confidence": 1,
            "rationale": "test",
        }
    )
    intent = await intent_provider.classify("hello")
    assert intent.intent == "general"

    config_provider = providers_openai.OpenAIConfigAssistantProvider("model-b", None)
    config_client = Client(
        {
            "summary": "done",
            "proposals": {
                "feature": "config-file",
                "title": "Config",
                "target_file": "klipperai/config.cfg",
                "config": "[include config.cfg]",
                "rationale": "test",
            },
        }
    )
    config_provider._client = config_client
    config_payload = ConfigPromptPayload(
        user_message="config",
        snapshot=payload.config_snapshot,
        target=ConfigRequestTarget(feature="fan", rationale="because"),
        profile=PrinterProfile(),
    )
    config_result = await config_provider.propose(config_payload)
    assert config_result.proposals[0].feature == "generic"
    assert "No runtime context collected." in config_client.calls[0]["user_prompt"]


@pytest.mark.asyncio
async def test_json_client_stub_router_and_lookup(monkeypatch) -> None:
    assert (
        await providers_stub.StubIntentRouterProvider().classify("Where is my fan? ")
    ).intent == "config_lookup"

    lookup = await providers_config_stub.StubConfigAssistantProvider().propose(
        ConfigPromptPayload(
            user_message="where",
            snapshot=_snapshot_with("fan"),
            target=ConfigRequestTarget(feature="fan", intent="locate", rationale="test"),
            profile=PrinterProfile(),
        )
    )
    assert lookup.proposals == []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '```json\n{"summary": "ok"}\n```'}}]}

    class AsyncClient:
        def __init__(self, **kwargs):
            assert kwargs["timeout"] == 60.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            assert url.endswith("/chat/completions")
            assert kwargs["headers"]["Authorization"] == "Bearer secret"
            return Response()

    monkeypatch.setattr(providers_json_client.httpx, "AsyncClient", AsyncClient)
    client = providers_json_client.OpenAIJsonClient("model", "secret")
    assert await client.complete_json(system_prompt="system", user_prompt="user") == {
        "summary": "ok"
    }
    with pytest.raises(ValueError, match="no API key"):
        await providers_json_client.OpenAIJsonClient("model", None).complete_json(
            system_prompt="s", user_prompt="u"
        )


def test_llm_normalization_helpers_cover_malformed_shapes() -> None:
    assert providers_models.ConfigAssistantOutput(summary=None, proposals=None).proposals == []
    proposal = {
        "feature": "fan",
        "title": "x",
        "target_file": "x",
        "config": "x",
        "rationale": "x",
    }
    assert (
        len(providers_models.ConfigAssistantOutput(summary="x", proposals=proposal).proposals) == 1
    )
    assert providers_models.ConfigAssistantOutput(summary="x", proposals="bad").proposals == []
    with pytest.raises(ValueError, match="not a JSON object"):
        providers_normalization._parse_json_object("[]")

    unchanged = {"proposals": "bad"}
    assert (
        providers_normalization._normalize_config_assistant_data(unchanged, fallback_feature="fan")
        is unchanged
    )
    normalized = providers_normalization._normalize_config_assistant_data(
        {"proposals": ["raw", {**proposal, "feature": "unknown"}]},
        fallback_feature="fan",
    )
    assert normalized["proposals"] == ["raw", proposal]

    assert providers_normalization._coerce_string_list(None) == []
    assert providers_normalization._coerce_string_list(" value ") == ["value"]
    assert providers_normalization._coerce_string_list(" ") == []
    assert providers_normalization._coerce_string_list(12) == ["12"]
    assert providers_normalization._coerce_string_list([None, {"summary": "cause"}]) == ["cause"]
    assert providers_normalization._stringify_llm_item({"count": 2}) == "count: 2"
    assert providers_normalization._stringify_llm_item({"nested": {"x": object()}}).startswith(
        "{'nested':"
    )
    assert providers_normalization._stringify_llm_item(["one", "two"]) == "one; two"


def test_provider_factories_select_openai_and_stub(monkeypatch) -> None:
    monkeypatch.setattr(
        providers_factory, "OpenAIDiagnosisProvider", lambda **kwargs: ("diagnosis", kwargs)
    )
    monkeypatch.setattr(
        providers_factory, "OpenAIConfigAssistantProvider", lambda **kwargs: ("config", kwargs)
    )
    monkeypatch.setattr(
        providers_factory, "OpenAIIntentRouterProvider", lambda **kwargs: ("intent", kwargs)
    )
    settings = Settings(
        llm_provider=" OPENAI ", openai_api_key=SecretStr("secret"), openai_model="model"
    )
    assert providers_factory.build_diagnosis_provider(settings)[1]["api_key"] == "secret"
    assert providers_factory.build_config_provider(settings)[1]["model"] == "model"
    assert providers_factory.build_intent_router(settings)[1]["api_key"] == "secret"

    stub = Settings(llm_provider="stub")
    assert isinstance(
        providers_factory.build_diagnosis_provider(stub), providers_stub.StubDiagnosisProvider
    )
    assert isinstance(
        providers_factory.build_config_provider(stub),
        providers_config_stub.StubConfigAssistantProvider,
    )
    assert isinstance(
        providers_factory.build_intent_router(stub), providers_stub.StubIntentRouterProvider
    )
