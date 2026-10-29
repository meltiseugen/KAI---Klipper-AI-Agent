"""Workflow output contracts and provider wire format, without a live provider."""

import json

import pytest
from pydantic import ValidationError
from test_agent import ScriptedModel
from test_agent import tool_context as tool_context
from test_agent_providers import client_for

from klipperai_agent.agent.models import AgentLimits, ModelTurn
from klipperai_agent.agent.response_contracts import (
    response_format,
    response_model,
    select_workflow,
    workflow_prompt,
)
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.domain.evidence import ArtifactInput
from klipperai_agent.domain.investigation import InvestigationRequest
from klipperai_agent.providers.responses import OpenAIAgentModel


@pytest.mark.parametrize(
    "message,mode,workflow",
    [
        ("What is Klipper?", "chat", "general"),
        ("Why did it fail?", "chat", "diagnosis"),
        ("Inspect state", "debug", "diagnosis"),
        ("Where is [fan] defined?", "chat", "config_explanation"),
        ("Explain [extruder]", "chat", "config_explanation"),
        ("Explain how to add a fan", "chat", "config_explanation"),
        ("Why does [fan] fail?", "chat", "diagnosis"),
        ("Explain why [fan] failed", "chat", "diagnosis"),
        ("Why does the fan fail when I change its settings?", "chat", "diagnosis"),
        ("Disable [fan]", "chat", "config_draft"),
        ("Create a fan config", "debug", "config_draft"),
        ("fan proposal", "chat", "config_draft"),
        ("Change [fan] kick_start_time", "chat", "config_draft"),
    ],
)
def test_selects_contract_without_model_classification(message, mode, workflow):
    assert select_workflow(InvestigationRequest(user_message=message, mode=mode)) == workflow
    assert workflow in workflow_prompt(workflow)
    assert response_model(workflow).parse_obj({"response": "  Answer  "}).response == "Answer"


def test_log_attachment_selects_diagnosis_but_config_attachment_does_not():
    assert (
        select_workflow(
            InvestigationRequest(
                user_message="Read this",
                artifacts=[ArtifactInput(kind="moonraker_log", content="example")],
            )
        )
        == "diagnosis"
    )
    assert (
        select_workflow(
            InvestigationRequest(
                user_message="Hi",
                artifacts=[ArtifactInput(kind="config_snippet", content="[printer]")],
            )
        )
        == "general"
    )


@pytest.mark.parametrize("workflow", ["general", "diagnosis", "config_explanation", "config_draft"])
def test_strict_schema_has_closed_objects_required_fields_and_no_review_output(workflow):
    format = response_format(workflow)
    assert format["type"] == "json_schema" and format["strict"]

    def inspect(value):
        if isinstance(value, dict):
            assert "default" not in value
            if value.get("type") == "object":
                assert value["additionalProperties"] is False
                assert set(value["required"]) == set(value["properties"])
            for item in value.values():
                inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)

    inspect(format["schema"])
    assert "review" not in format["schema"]["definitions"]["DraftProposal"]["properties"]
    assert "title" in format["schema"]["definitions"]["DraftProposal"]["properties"]
    if workflow == "diagnosis":
        assert "hypotheses" in format["schema"]["properties"]
    if workflow != "config_draft":
        assert format["schema"]["properties"]["config_proposals"]["maxItems"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"response": " "},
        {"response": 42},
        {"response": "ok", "findings": []},
        {
            "response": "ok",
            "config_proposals": [
                {
                    "title": "No",
                    "target_file": "printer.cfg",
                    "config": "[fan]",
                    "rationale": "Unrequested",
                }
            ],
        },
        {"response": "ok", "claims": [{"claim": "Made up", "evidence_refs": []}]},
    ],
)
def test_general_contract_rejects_invalid_or_unrequested_outputs(payload):
    with pytest.raises(ValidationError):
        response_model("general").parse_obj(payload)


@pytest.mark.asyncio
async def test_provider_sends_selected_strict_schema_and_preserves_opaque_output():
    requests = []
    opaque = [{"type": "reasoning", "encrypted_content": "unchanged", "summary": []}]
    client = client_for({"status": "completed", "output": opaque}, requests=requests)
    try:
        turn = await OpenAIAgentModel(client).respond(
            [], [], response_format=response_format("diagnosis")
        )
        assert turn.output == opaque
        assert requests[0]["text"]["format"] == response_format("diagnosis")
        assert requests[0]["store"] is False
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_agent_repairs_bad_claim_reference_and_keeps_workflow_and_gaps(tool_context):
    invalid = {
        "response": "Found it",
        "claims": [
            {
                "claim": "Unknown",
                "evidence_refs": [{"evidence_id": "fabricated", "start_line": 1, "end_line": 1}],
            }
        ],
    }
    valid = {
        "response": "Fault remains unconfirmed",
        "hypotheses": ["Link issue is possible"],
        "missing_evidence": ["Incident clock anchor"],
    }
    model = ScriptedModel(
        ModelTurn([], text=json.dumps(invalid)), ModelTurn([], text=json.dumps(valid))
    )
    result = await AgentWorkflow(model, tool_context.moonraker, AgentLimits()).ainvoke(
        {"user_message": "Diagnose failure"}, context=tool_context.services
    )
    assert result["agent_status"] == "completed"
    assert result["hypotheses"] == valid["hypotheses"]
    assert result["missing_evidence"] == valid["missing_evidence"]
    assert len(model.conversations) == 2
    assert "available evidence IDs" in model.conversations[1][-1]["content"]
