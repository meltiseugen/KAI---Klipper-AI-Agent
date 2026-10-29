"""New runtime findings reach both diagnostic workflows without a live provider."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from klipperai_agent.agent.models import AgentLimits, ModelTurn
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.config.collector import ConfigCollector
from klipperai_agent.diagnostics.models import DiagnosticsSnapshot
from klipperai_agent.diagnostics.rules import RuleEngine
from klipperai_agent.domain.evidence import ArtifactInput
from klipperai_agent.profile.models import PrinterProfile
from klipperai_agent.providers.models import DiagnosisLLMOutput
from klipperai_agent.workflows.engine import build_diagnosis_graph


@pytest.mark.asyncio
@pytest.mark.parametrize("workflow_name", ["agent", "single_pass"])
async def test_new_fault_families_reach_provider_context_and_public_findings(
    tmp_path, workflow_name
):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "printer.cfg").write_text("[printer]\nkinematics: cartesian\n")
    artifact = ArtifactInput(
        kind="klippy_log",
        label="supplied-klippy-excerpt",
        content="\n".join(
            [
                "Heater extruder not heating at expected rate",
                "No trigger on probe after full movement",
                "TMC 'stepper_x' reports error: GSTAT: 00000001 reset=1",
                "MCU Protocol error",
                "Move out of range: 310.000 20.000 5.000 [0.000]",
            ]
        ),
    )
    collector = SimpleNamespace(
        collect=AsyncMock(return_value=DiagnosticsSnapshot(True, {}, [artifact]))
    )
    model_provider = SimpleNamespace(
        analyze=AsyncMock(
            return_value=DiagnosisLLMOutput(
                summary="The model reviewed the reported fault families.",
                likely_causes=[],
                recommended_actions=[],
                follow_up_questions=[],
            )
        )
    )
    services = SimpleNamespace(
        collector=collector,
        config_collector=ConfigCollector(tmp_path),
        rules=RuleEngine(),
        profile=PrinterProfile(),
        llm=model_provider,
    )
    state = {
        "user_message": "Explain the reported failures and the evidence needed to investigate.",
        "mode": "debug",
        "artifacts": [artifact.model_dump()],
    }
    if workflow_name == "agent":
        model = SimpleNamespace(
            respond=AsyncMock(
                return_value=ModelTurn([], text=json.dumps({"response": "Review the evidence."}))
            )
        )
        moonraker = SimpleNamespace(
            get_printer_info=AsyncMock(return_value={"state": "shutdown"}),
            list_printer_objects=AsyncMock(return_value=[]),
        )
        result = await AgentWorkflow(model, moonraker, AgentLimits()).ainvoke(
            state, context=services
        )
        starting_context = json.loads(model.respond.await_args.args[0][1]["content"])
        observed_findings = starting_context["diagnostics"]["findings"]
        assert result["agent_status"] == "completed"
        model_provider.analyze.assert_not_called()
    else:
        result = await build_diagnosis_graph().ainvoke(state, context=services)
        observed_findings = [
            item.model_dump() for item in model_provider.analyze.await_args.args[0].findings
        ]
        assert "model reviewed" in result["response_text"]

    expected_codes = {
        "heater_heating_failure",
        "homing_no_trigger",
        "tmc_driver_fault",
        "mcu_protocol_mismatch",
        "move_out_of_range",
    }
    assert {item["code"] for item in result["findings"]} == expected_codes
    assert {item["code"] for item in observed_findings} == expected_codes
    assert all(item["source"] == artifact.label for item in result["findings"])
    assert all("Collected excerpt line" in item["evidence"] for item in result["findings"])
    assert not result.get("patch_proposals")
    collector.collect.assert_awaited_once()
