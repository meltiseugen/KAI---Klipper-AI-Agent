from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from klipperai_agent.config.models import ConfigDocument, ConfigSnapshot
from klipperai_agent.diagnostics.evidence import config_evidence, diagnostic_evidence, link_findings
from klipperai_agent.diagnostics.models import DiagnosticsSnapshot
from klipperai_agent.diagnostics.rules import RuleEngine
from klipperai_agent.domain.artifacts import (
    CollectedArtifact,
    normalize_artifact,
    normalize_input,
    public_evidence_blocks,
)
from klipperai_agent.domain.evidence import ArtifactInput, IssueFinding, SourceCitation
from klipperai_agent.domain.investigation import Evidence
from klipperai_agent.domain.redaction import redact_text

STAMP = "2026-10-27T12:00:00+00:00"


def finding(**kwargs):
    return IssueFinding(
        code="fault",
        severity="high",
        source="klippy.log",
        summary="A fault",
        evidence="Collected excerpt line 301: Heater extruder not heating at expected rate",
        proposed_fix="Inspect manually",
        **kwargs,
    )


def test_typed_artifact_normalizes_redacts_and_keeps_identity_and_source_scope():
    artifact = normalize_input(
        ArtifactInput.parse_obj(
            {
                "kind": "klippy_log",
                "label": "klippy.log",
                "content": "api_key=private-value\nLost communication with MCU",
                "origin": "host",
                "freshness": "current_snapshot",
            }
        ),
        observed_at=STAMP,
    )
    assert artifact.origin == "user" and artifact.freshness == "user_supplied"
    assert artifact.line_basis == "excerpt" and artifact.start_line == 1
    assert "private-value" not in artifact.json()
    assert artifact.observed_at == STAMP and artifact.original_characters > 0
    copied = CollectedArtifact.parse_obj(artifact.model_dump())
    assert copied.id == artifact.id and copied.prompt_value()["content"] == artifact.content
    with pytest.raises(ValidationError):
        CollectedArtifact(source="bad", content="body", kind="arbitrary_path")
    structured = normalize_artifact(
        source="/printer/info",
        content={"state": "ready", "api_key": "private-key"},
        observed_at=STAMP,
        origin="moonraker",
        freshness="current_snapshot",
    )
    assert structured.content_format == "json"
    assert structured.prompt_value()["content"]["state"] == "ready"
    assert "private-key" not in structured.json()
    assert (
        normalize_artifact(
            source="/printer/info",
            content={"state": "ready", "api_key": "private-key"},
            observed_at=STAMP,
            origin="moonraker",
        ).id
        == structured.id
    )
    with pytest.raises(ValueError):
        normalize_artifact(source="bad", content={"cpu": float("nan")})


def test_clipping_is_explicit_and_public_blocks_have_bounded_redacted_citations():
    citation = SourceCitation(
        label="source",
        path="log",
        url="https://docs.example/log",
        excerpt="api_key=private-value\n" + "quoted " * 1000,
    )
    artifact = normalize_artifact(
        source="large", content={"value": "x" * 20000}, observed_at=STAMP, citations=[citation]
    )
    assert artifact.status == "partial" and artifact.content_format == "text"
    assert len(artifact.content) <= 16000 and artifact.original_characters > 20000
    assert "truncated" in artifact.prompt_value()["content"]
    records = [artifact, artifact] + [
        normalize_artifact(source=f"s{i}", content="body") for i in range(30)
    ]
    blocks = public_evidence_blocks(records)
    assert len(blocks) == 24 and len({item.id for item in blocks}) == 24
    assert blocks[0].id == artifact.id and blocks[0].observed_at == STAMP
    assert len(blocks[0].content) <= 2000 and len(blocks[0].citations[0].excerpt) <= 500
    assert "private-value" not in json.dumps([item.model_dump() for item in blocks])
    unavailable = normalize_artifact(source="missing", content="details " * 1000, unavailable=True)
    assert public_evidence_blocks([unavailable])[0].status == "unavailable"


def test_focused_finding_quotes_survive_long_source_clipping_and_keep_line_basis():
    raw = ArtifactInput(
        kind="klippy_log",
        label="klippy.log",
        content="older entry\n" * 2000 + "Heater extruder not heating at expected rate",
    )
    source = normalize_input(raw, observed_at=STAMP)
    artifacts = [source]
    report = RuleEngine().analyze([raw])[0]
    result = link_findings([report], artifacts)
    quote = next(item for item in artifacts if item.id == result[0].evidence_ids[0])
    assert quote.start_line == 2001 and quote.line_basis == "excerpt"
    assert "Heater extruder" in quote.content and quote.citations[0].line_number == 2001
    assert quote.observed_at == source.observed_at
    assert len(artifacts) == 2
    link_findings(result, artifacts)
    assert len({item.id for item in artifacts}) == len(artifacts)
    unmatched = finding().copy(update={"source": "not-collected"})
    assert link_findings([unmatched], artifacts)[0].evidence_ids == []
    plain = normalize_artifact(source="klippy.log", label="klippy.log", content="fault")
    assert link_findings([finding().copy(update={"evidence": "fault"})], [plain])[0].evidence_ids


def test_snapshots_preserve_collection_metadata_through_workflow_state():
    snapshot = DiagnosticsSnapshot(
        True, {"state": "ready"}, [ArtifactInput(label="log", content="before")], observed_at=STAMP
    )
    snapshot.artifacts[0].content = "after"
    restored = DiagnosticsSnapshot.from_state(snapshot.to_state())
    assert restored.normalized_artifacts[0].content == "after"
    assert restored.normalized_artifacts[0].id == snapshot.normalized_artifacts[0].id
    assert all(item.observed_at == STAMP for item in diagnostic_evidence(restored))
    assert "after" in restored.to_prompt_block()
    config = ConfigSnapshot(
        "printer.cfg",
        [ConfigDocument("printer.cfg", "[printer]\n", ["printer"])],
        observed_at=STAMP,
    )
    assert (
        config_evidence(config)[0].id
        == config_evidence(ConfigSnapshot.from_state(config.to_state()))[0].id
    )
    assert config_evidence(config)[0].line_basis == "file"
    evidence = Evidence.parse_obj(
        normalize_artifact(source="tool", content={"value": "x" * 2000}).model_dump()
    ).copy(update={"content": "excerpt"})
    historical = evidence.historical_context()
    assert historical["artifact"]["freshness"] == "historical"
    assert (
        historical["artifact"]["origin"] == "memory"
        and historical["artifact"]["status"] == "partial"
    )
    assert historical["artifact"]["content_format"] == "text"


def test_impact_rank_is_independent_from_observation_confidence_and_redaction_scales():
    high = finding(severity_rank=999)
    assert high.severity_rank == 3 and high.confidence == "unknown"
    assert finding().copy(update={"severity": "low"}).confidence == "unknown"
    text = "x" * 80000 + " https://name:private-password@example.test/path"
    assert "private-password" not in redact_text(text)
    assert len(redact_text("x" * 80000)) == 80000
