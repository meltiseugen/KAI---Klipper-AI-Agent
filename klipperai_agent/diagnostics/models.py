from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from klipperai_agent.domain.evidence import ArtifactInput


@dataclass(slots=True)
class DiagnosticsSnapshot:
    moonraker_reachable: bool
    moonraker_info: dict[str, Any] | None
    artifacts: list[ArtifactInput]
    notes: list[str] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        sections: list[str] = []

        if self.moonraker_info:
            sections.append(f"Moonraker server info:\n{self.moonraker_info}")
        if self.notes:
            sections.append("Collector notes:\n" + "\n".join(self.notes))

        if self.artifacts:
            artifact_blocks = [
                f"[{artifact.kind}] {artifact.label}\n{artifact.prompt_excerpt()}"
                for artifact in self.artifacts
            ]
            sections.append("Artifacts:\n" + "\n\n".join(artifact_blocks))

        return "\n\n".join(sections) if sections else "No runtime context collected."
