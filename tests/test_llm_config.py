from __future__ import annotations

import pytest

from kai_agent.config.models import ConfigRequestTarget, ConfigSnapshot
from kai_agent.config.requests import ConfigPromptPayload
from kai_agent.config.templates.catalog import ProposalCatalog
from kai_agent.profile.models import PrinterProfile
from kai_agent.providers.openai import OpenAIConfigAssistantProvider


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("feature", "expected_target"),
    [
        ("fan", "kai/fan.cfg"),
        ("macro", "kai/macros.cfg"),
        ("sensor", "kai/sensor.cfg"),
        ("probe", "kai/probe.cfg"),
        ("heater", "kai/heater.cfg"),
        ("input_shaper", "kai/input_shaper.cfg"),
        ("bed_mesh", "kai/bed_mesh.cfg"),
        ("filament", "kai/filament.cfg"),
        ("canbus", "kai/canbus.cfg"),
        ("stepper", "kai/stepper.cfg"),
        ("extruder", "kai/extruder.cfg"),
        ("generic", "kai/custom.cfg"),
    ],
)
async def test_template_catalog_returns_a_proposal_for_each_feature(
    feature: str,
    expected_target: str,
) -> None:
    catalog = ProposalCatalog()
    payload = ConfigPromptPayload(
        user_message=f"Generate me a {feature} config",
        snapshot=ConfigSnapshot(root_file=None, documents=[], notes=[]),
        target=ConfigRequestTarget(feature=feature, rationale="test"),
        profile=PrinterProfile(),
    )

    proposal = catalog.build(payload)
    assert proposal.target_file == expected_target


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
                    "config": "[include kai/*.cfg]\n",
                    "rationale": "Load managed KAI snippets.",
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
        user_message="Add the KAI include",
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
                    "target_file": "kai/fan.cfg",
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
