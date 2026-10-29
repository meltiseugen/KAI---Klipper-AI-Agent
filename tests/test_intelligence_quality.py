"""Automated replay of additional deterministic guards and manual recovery plans."""

import json

import pytest
from test_agent import ScriptedModel, answer
from test_agent import tool_context as tool_context

from klipperai_agent.agent.models import AgentLimits
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.diagnostics.playbooks import recovery_playbook
from klipperai_agent.diagnostics.rules import RuleEngine
from klipperai_agent.domain.evidence import ArtifactInput

CASES = [
    ("Extrude below minimum temp", "cold_extrusion", "extrusion-guard"),
    (
        "Move exceeds maximum extrusion (0.800mm^2 vs 0.640mm^2)",
        "extrusion_cross_section",
        "extrusion-guard",
    ),
    (
        "Extrude only move too long (60.000mm vs 50.000mm)",
        "extrude_only_distance",
        "extrusion-guard",
    ),
    ("Must home axis first: 10 20 30 [0]", "must_home_first", "homing-probe"),
    ("Must home before probe", "must_home_first", "homing-probe"),
    ("Probe samples exceed samples_tolerance", "probe_samples_tolerance", "probe-repeatability"),
]


@pytest.mark.parametrize("message,code,plan", CASES)
def test_new_failure_signatures_have_citations_and_manual_recovery(message, code, plan):
    findings = RuleEngine().analyze(
        [ArtifactInput(kind="klippy_log", label="supplied", content="\n" + message)]
    )
    assert len(findings) == 1
    finding = findings[0]
    assert finding.code == code
    assert finding.confidence_scope == "observation"
    assert finding.citations[0].line_number == finding.citations[0].end_line == 2
    assert finding.citations[0].line_basis == "excerpt"
    assert finding.citations[0].excerpt == message
    assert finding.recovery.id == plan and finding.recovery.manual_only
    assert finding.recovery.required_evidence and finding.recovery.steps
    assert finding.recovery.verification and finding.recovery.stop_conditions


@pytest.mark.parametrize(
    "message",
    [
        "Probe samples exceed tolerance. Retrying...",
        "samples_tolerance: 0.1",
        "Extruder temperature: 200",
        "Extrude below minimum temperature example",
        "Move exceeds nominal speed",
        "Must home before printing",
        "# Extrude only move too long",
        "; Must home axis first",
        "===== Config file =====\nRESPOND MSG='Extrude below minimum temp'\n=======================",
    ],
)
def test_near_matches_retries_comments_and_config_dumps_do_not_become_new_faults(message):
    assert RuleEngine().analyze([ArtifactInput(kind="klippy_log", content=message)]) == []


def test_playbooks_are_independent_and_do_not_turn_unknown_codes_into_diagnoses():
    assert recovery_playbook("unknown") is None
    first = recovery_playbook("adc_out_of_range")
    first.steps.clear()
    assert recovery_playbook("adc_out_of_range").steps


@pytest.mark.asyncio
async def test_legacy_evidence_is_checked_when_automatic_log_collection_fails(
    tool_context,
):
    artifact = ArtifactInput(
        kind="klippy_log", label="legacy-evidence", content="Must home axis first"
    )
    tool_context.services.collector.collect.side_effect = RuntimeError("Log collection unavailable")
    model = ScriptedModel(answer())
    workflow = AgentWorkflow(model, tool_context.moonraker, AgentLimits())
    result = await workflow.ainvoke(
        {"user_message": "Investigate this printer failure", "artifacts": [artifact.model_dump()]},
        context=tool_context.services,
    )
    payload = json.loads(model.conversations[0][1]["content"])
    assert "error" in payload["diagnostics"]
    assert payload["deterministic_findings"][0]["recovery"]["id"] == "homing-probe"
    assert result["workflow"] == "diagnosis"
    citation = result["findings"][0]["citations"][0]
    assert citation["line_number"] == 1 and citation["line_basis"] == "excerpt"
    assert citation["evidence_id"] and citation["observed_at"]
    assert citation in result["source_citations"]
    tool_context.services.collector.collect.assert_awaited_once_with(
        [artifact], include_host_logs=True, include_host_system=False
    )
