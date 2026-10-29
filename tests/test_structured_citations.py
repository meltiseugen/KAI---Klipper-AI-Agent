"""Citations are resolved from retained source bytes, not model-authored paths."""

import json

import pytest
from test_agent import ScriptedModel
from test_agent import tool_context as tool_context
from test_evidence_pipeline import wire_diagnostics
from test_investigations import persistent_service as persistent_service

from klipperai_agent.agent.claim_citations import resolve_claims
from klipperai_agent.agent.models import AgentLimits, ModelTurn
from klipperai_agent.agent.response_contracts import CitedClaim
from klipperai_agent.agent.workflow import AgentWorkflow
from klipperai_agent.config.models import ConfigDocument, ConfigPlaceholder, ConfigSnapshot
from klipperai_agent.contracts.api import ChatRequest
from klipperai_agent.diagnostics.evidence import config_evidence, link_findings
from klipperai_agent.diagnostics.rules import RuleEngine
from klipperai_agent.domain.artifacts import normalize_artifact
from klipperai_agent.domain.evidence import SourceCitation
from klipperai_agent.domain.investigation import Evidence


def source(**updates):
    values = dict(
        source="config:printer.cfg",
        label="printer.cfg",
        origin="config",
        freshness="saved_configuration",
        kind="config_file",
        content="; header\n  [extruder]\nstep_pin: PA1\ndir_pin: PA2",
        line_basis="file",
        start_line=1,
        config_revision="revision",
        observed_at="2026-10-27T12:00:00+00:00",
    )
    values.update(updates)
    return Evidence.parse_obj(normalize_artifact(**values).model_dump())


def claim(item, start=3, end=4):
    return CitedClaim(
        claim="These pin options are present on disk.",
        evidence_refs=[{"evidence_id": item.id, "start_line": start, "end_line": end}],
    )


def test_exact_config_ranges_keep_section_revision_and_collection_date():
    item = source()
    resolved = resolve_claims([claim(item)], [item])[0]
    citation = resolved.citations[0]
    assert citation.excerpt == "step_pin: PA1\ndir_pin: PA2"
    assert citation.section == "extruder"
    assert citation.line_number == 3 and citation.end_line == 4
    assert citation.line_basis == "file" and citation.evidence_id == item.id
    assert citation.config_revision == "revision" and citation.observed_at == item.observed_at


def test_excerpt_offsets_do_not_become_original_file_lines():
    item = source(
        source="log-excerpt",
        origin="user",
        kind="klippy_log",
        content="first\nsecond\nthird",
        line_basis="excerpt",
        start_line=20,
        config_revision=None,
    )
    citation = resolve_claims([claim(item, 21, 22)], [item])[0].citations[0]
    assert citation.excerpt == "second\nthird" and citation.line_basis == "excerpt"
    assert citation.section is None


def test_no_range_selects_only_trusted_source_citations_and_no_mutation():
    trusted = SourceCitation(
        label="Exact section",
        path="printer.cfg",
        line_number=2,
        section="extruder",
        excerpt="[extruder]",
        line_basis="file",
    )
    item = source(citations=[trusted])
    citation = resolve_claims([claim(item, 0, 0)], [item])[0].citations[0]
    assert citation.path == "printer.cfg" and citation.section == "extruder"
    assert citation.evidence_id == item.id
    assert trusted.evidence_id is None


def test_config_findings_link_to_the_observed_section_and_revision():
    snapshot = ConfigSnapshot(
        "printer.cfg",
        [ConfigDocument("printer.cfg", "# header\n[extruder]\nstep_pin: <PIN>", ["extruder"])],
        placeholders=[
            ConfigPlaceholder("printer.cfg", 3, "step_pin: <PIN>", "<PIN>", "extruder", "step_pin")
        ],
    )
    findings = link_findings(
        RuleEngine().analyze([], config_snapshot=snapshot), config_evidence(snapshot)
    )
    citation = findings[0].citations[0]
    assert citation.section == "extruder" and citation.line_basis == "file"
    assert citation.line_number == 3 and citation.config_revision == snapshot.revision()


@pytest.mark.parametrize(
    "updates,start,end",
    [
        ({"unavailable": True}, 3, 3),
        ({}, 0, 0),
        ({}, 0, 2),
        ({}, 4, 3),
        ({}, 3, 9),
        ({"line_basis": "none"}, 1, 1),
        ({"content": {"state": "shutdown"}}, 1, 1),
        ({"content": "line\n...[truncated]..."}, 2, 2),
        ({"content": "x" * 4001}, 1, 1),
        ({"content": "line\n" * 130}, 1, 121),
    ],
)
def test_rejects_unavailable_missing_unscoped_clipped_or_invalid_ranges(updates, start, end):
    item = source(**updates)
    with pytest.raises(ValueError):
        resolve_claims([claim(item, start, end)], [item])


@pytest.mark.asyncio
async def test_agent_resolves_a_config_claim_and_returns_server_owned_citations(tool_context):
    class Model(ScriptedModel):
        async def respond(self, conversation, tools, *, response_format=None):
            payload = json.loads(conversation[1]["content"])
            item = payload["active_config"]["files"][0]["artifact"]
            return ModelTurn(
                [],
                text=json.dumps(
                    {
                        "response": "The extruder section is in printer.cfg.",
                        "config_scope": "on_disk",
                        "claims": [
                            {
                                "claim": "The extruder section is present.",
                                "evidence_refs": [
                                    {"evidence_id": item["id"], "start_line": 3, "end_line": 4}
                                ],
                            }
                        ],
                    }
                ),
            )

    result = await AgentWorkflow(Model(), tool_context.moonraker, AgentLimits()).ainvoke(
        {"user_message": "Explain [extruder]"}, context=tool_context.services
    )
    assert result["workflow"] == "config_explanation"
    citation = result["answer_claims"][0]["citations"][0]
    assert citation["section"] == "extruder" and citation["path"] == "printer.cfg"
    assert citation in result["source_citations"]


@pytest.mark.asyncio
async def test_grounded_claims_and_playbooks_survive_http_projection_and_saved_history(
    persistent_service,
):
    service, _ = persistent_service
    printer = wire_diagnostics(service)

    class Model:
        async def respond(self, conversation, tools, *, response_format=None):
            payload = json.loads(conversation[1]["content"])
            item = payload["artifacts"][0]
            return ModelTurn(
                [],
                text=json.dumps(
                    {
                        "response": "A homing guard rejected this command.",
                        "claims": [
                            {
                                "claim": "The uploaded excerpt reports missing homing state.",
                                "evidence_refs": [
                                    {"evidence_id": item["id"], "start_line": 1, "end_line": 1}
                                ],
                            }
                        ],
                        "missing_evidence": ["Originating macro"],
                        "hypotheses": ["Macro order needs checking"],
                    }
                ),
            )

    service.agent_workflow = AgentWorkflow(Model(), printer, AgentLimits())
    session = await service.create_ui_session()
    result = await service.chat(
        ChatRequest(
            session_id=session.session_id,
            message="Investigate",
            artifacts=[
                {"kind": "klippy_log", "label": "upload", "content": "Must home axis first"}
            ],
        )
    )
    assert result.answer_claims[0].citations[0].excerpt == "Must home axis first"
    assert result.findings[0].recovery.id == "homing-probe"
    saved = await service.investigations.get(result.thread_id)
    assert saved.turns[0].result.answer_claims == result.answer_claims
    assert saved.turns[0].result.findings[0].recovery == result.findings[0].recovery
    assert result.missing_evidence == ["Originating macro"]
    assert result.hypotheses == ["Macro order needs checking"]
