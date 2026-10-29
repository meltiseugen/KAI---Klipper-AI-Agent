from __future__ import annotations

from dataclasses import dataclass, field

from klipperai_agent.config.models import ConfigRequestTarget, ConfigSnapshot
from klipperai_agent.diagnostics.evidence import config_evidence, diagnostic_evidence
from klipperai_agent.diagnostics.models import DiagnosticsSnapshot
from klipperai_agent.domain.artifacts import CollectedArtifact, normalize_artifact
from klipperai_agent.profile.models import PrinterProfile


@dataclass(slots=True)
class ConfigPromptPayload:
    user_message: str
    snapshot: ConfigSnapshot
    target: ConfigRequestTarget
    profile: PrinterProfile
    runtime_snapshot: DiagnosticsSnapshot | None = None
    conversation_context: str = ""
    context_artifacts: list[CollectedArtifact] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.context_artifacts = [
            *config_evidence(self.snapshot),
            *(diagnostic_evidence(self.runtime_snapshot) if self.runtime_snapshot else []),
            normalize_artifact(
                source="saved_printer_profile",
                kind="printer_profile",
                label="Saved printer profile",
                origin="saved_profile",
                freshness="saved_configuration",
                content=self.profile.to_summary(),
            ),
        ]
