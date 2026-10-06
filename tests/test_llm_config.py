from __future__ import annotations

import pytest

from klipperai_agent.config.models import ConfigRequestTarget, ConfigSnapshot
from klipperai_agent.config.requests import ConfigPromptPayload
from klipperai_agent.profile.models import PrinterProfile
from klipperai_agent.providers.config_stub import StubConfigAssistantProvider
from klipperai_agent.providers.openai import OpenAIConfigAssistantProvider


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("feature", "expected_target"),
    [
        ("fan", "klipperai/fan.cfg"),
        ("macro", "klipperai/macros.cfg"),
        ("sensor", "klipperai/sensor.cfg"),
        ("probe", "klipperai/probe.cfg"),
        ("heater", "klipperai/heater.cfg"),
        ("input_shaper", "klipperai/input_shaper.cfg"),
        ("bed_mesh", "klipperai/bed_mesh.cfg"),
        ("filament", "klipperai/filament.cfg"),
        ("canbus", "klipperai/canbus.cfg"),
        ("stepper", "klipperai/stepper.cfg"),
        ("extruder", "klipperai/extruder.cfg"),
        ("generic", "klipperai/custom.cfg"),
    ],
)
async def test_stub_config_provider_returns_a_proposal_for_each_feature(
    feature: str,
    expected_target: str,
) -> None:
    provider = StubConfigAssistantProvider()
    payload = ConfigPromptPayload(
        user_message=f"Generate me a {feature} config",
        snapshot=ConfigSnapshot(root_file=None, documents=[], notes=[]),
        target=ConfigRequestTarget(feature=feature, rationale="test"),
        profile=PrinterProfile(),
    )

    result = await provider.propose(payload)

    assert result.proposals
    assert result.proposals[0].target_file == expected_target


class _FakeOpenAIJsonClient:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.system_prompt = ""

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, object]:
        self.system_prompt = system_prompt
        return self.response


@pytest.mark.asyncio
async def test_openai_config_provider_normalizes_include_feature_to_generic() -> None:
    client = _FakeOpenAIJsonClient(
        {
            "summary": "Add a managed include.",
            "proposals": [
                {
                    "feature": "include",
                    "title": "Managed include",
                    "target_file": "printer.cfg",
                    "config": "[include klipperai/*.cfg]\n",
                    "rationale": "Load managed KlipperAI snippets.",
                    "assumptions": [],
                    "warnings": [],
                }
            ],
            "next_actions": [],
            "follow_up_questions": [],
        }
    )
    provider = OpenAIConfigAssistantProvider(model="test", api_key="test")
    provider._client = client
    payload = ConfigPromptPayload(
        user_message="Add the KlipperAI include",
        snapshot=ConfigSnapshot(root_file=None, documents=[], notes=[]),
        target=ConfigRequestTarget(feature="generic", rationale="test"),
        profile=PrinterProfile(),
    )

    result = await provider.propose(payload)

    assert result.proposals[0].feature == "generic"
    assert "Use generic for include directives" in client.system_prompt


@pytest.mark.asyncio
async def test_openai_config_provider_uses_detected_feature_for_unknown_label() -> None:
    client = _FakeOpenAIJsonClient(
        {
            "summary": "Add cooling.",
            "proposals": [
                {
                    "feature": "cooling",
                    "title": "Part cooling fan",
                    "target_file": "klipperai/fan.cfg",
                    "config": "[fan]\npin: <FAN_PIN>\n",
                    "rationale": "Add part cooling.",
                    "assumptions": [],
                    "warnings": [],
                }
            ],
            "next_actions": [],
            "follow_up_questions": [],
        }
    )
    provider = OpenAIConfigAssistantProvider(model="test", api_key="test")
    provider._client = client
    payload = ConfigPromptPayload(
        user_message="Add a cooling fan",
        snapshot=ConfigSnapshot(root_file=None, documents=[], notes=[]),
        target=ConfigRequestTarget(feature="fan", rationale="test"),
        profile=PrinterProfile(),
    )

    result = await provider.propose(payload)

    assert result.proposals[0].feature == "fan"
