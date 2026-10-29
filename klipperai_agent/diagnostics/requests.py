from __future__ import annotations

from dataclasses import dataclass, field

from klipperai_agent.config.models import ConfigSnapshot
from klipperai_agent.diagnostics.evidence import config_evidence, diagnostic_evidence, link_findings
from klipperai_agent.diagnostics.models import DiagnosticsSnapshot
from klipperai_agent.domain.artifacts import CollectedArtifact, normalize_artifact
from klipperai_agent.domain.evidence import IssueFinding
from klipperai_agent.profile.models import PrinterProfile


@dataclass(slots=True)
class DiagnosisPromptPayload:
    user_message: str
    snapshot: DiagnosticsSnapshot
    config_snapshot: ConfigSnapshot
    findings: list[IssueFinding]
    profile: PrinterProfile
    conversation_context: str = ""
    context_artifacts: list[CollectedArtifact] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.context_artifacts = [
            *diagnostic_evidence(self.snapshot),
            *config_evidence(self.config_snapshot),
            normalize_artifact(
                source="saved_printer_profile",
                kind="printer_profile",
                label="Saved printer profile",
                origin="saved_profile",
                freshness="saved_configuration",
                content=self.profile.to_summary(),
            ),
        ]
        self.findings = link_findings(self.findings, self.context_artifacts)
