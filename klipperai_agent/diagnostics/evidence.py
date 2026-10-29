"""Pure conversion of collected snapshots and source-linked findings."""

from __future__ import annotations

import re

from klipperai_agent.config.models import ConfigSnapshot
from klipperai_agent.diagnostics.models import DiagnosticsSnapshot
from klipperai_agent.domain.artifacts import CollectedArtifact, normalize_artifact
from klipperai_agent.domain.evidence import IssueFinding, SourceCitation
from klipperai_agent.domain.investigation import Evidence


def config_evidence(snapshot: ConfigSnapshot) -> list[Evidence]:
    return [
        Evidence.parse_obj(
            normalize_artifact(
                source=f"config:{document.path}",
                label=document.path,
                kind="config_file",
                origin="config",
                freshness="saved_configuration",
                content=document.content,
                observed_at=snapshot.observed_at,
                config_revision=snapshot.revision(),
                partial=document.truncated,
                line_basis="file",
                start_line=1,
                citations=[
                    SourceCitation(
                        label=document.path,
                        path=document.path,
                        line_number=1,
                        excerpt=document.content[:1000],
                    )
                ],
                notes=["On-disk configuration; loaded firmware may use an older revision."],
            ).model_dump()
        )
        for document in snapshot.documents
    ]


def diagnostic_evidence(snapshot: DiagnosticsSnapshot) -> list[Evidence]:
    snapshot.refresh_artifacts()
    result = [Evidence.parse_obj(item.model_dump()) for item in snapshot.normalized_artifacts]
    if snapshot.moonraker_info is not None:
        result.append(
            Evidence.parse_obj(
                normalize_artifact(
                    source="/server/info",
                    label="Moonraker server info",
                    kind="printer_status",
                    origin="moonraker",
                    freshness="current_snapshot",
                    observed_at=snapshot.observed_at,
                    content=snapshot.moonraker_info,
                ).model_dump()
            )
        )
    return result


def link_findings(
    findings: list[IssueFinding], artifacts: list[CollectedArtifact]
) -> list[IssueFinding]:
    sources = list(artifacts)
    for finding in findings:
        config_line = re.search(r"^(.+\.cfg):(\d+)$", finding.source, re.I)
        source = config_line[1] if config_line else finding.source
        matching = [
            item
            for item in sources
            if not item.source.startswith("finding:")
            and (item.label == source or item.source in {source, f"config:{source}"})
        ]
        finding.evidence_ids = [item.id for item in matching[:4]]
        if matching:
            parent = matching[0]
            line = re.search(r"Collected excerpt line (\d+):", finding.evidence)
            number = int(line[1]) if line else int(config_line[2]) if config_line else None
            citation = SourceCitation(
                label=finding.source,
                path=parent.citations[0].path if parent.citations else parent.source,
                line_number=number,
                end_line=number,
                line_basis=parent.line_basis,
                evidence_id=parent.id,
                observed_at=parent.observed_at,
                config_revision=parent.config_revision,
                section=next((entry.section for entry in finding.citations if entry.section), None),
                excerpt=finding.evidence[:1200],
            )
            if parent.line_basis == "file" and number:
                for raw in parent.content.splitlines()[:number]:
                    header = re.match(r"^\s*\[([^]]+)\]", raw)
                    if header:
                        citation.section = header[1]
            finding.citations = [citation]
            quote = normalize_artifact(
                source=f"finding:{finding.code}:{source}",
                label=finding.source,
                kind=parent.kind,
                origin=parent.origin,
                freshness=parent.freshness,
                observed_at=parent.observed_at,
                content=finding.evidence,
                line_basis=parent.line_basis,
                start_line=number,
                config_revision=parent.config_revision,
                citations=[citation],
                notes=[
                    finding.confidence_reason,
                    "Focused finding excerpt; inspect the broader source for surrounding context.",
                ],
            )
            if all(item.id != quote.id for item in artifacts):
                artifacts.append(quote)
            finding.evidence_ids.insert(0, quote.id)
    return sorted(findings, key=lambda item: item.severity_rank, reverse=True)
