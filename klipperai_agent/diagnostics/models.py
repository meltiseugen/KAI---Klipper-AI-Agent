from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from klipperai_agent.domain.artifacts import CollectedArtifact, normalize_artifact, normalize_input
from klipperai_agent.domain.evidence import ArtifactInput
from klipperai_agent.domain.investigation import utc_now


@dataclass(slots=True)
class DiagnosticsSnapshot:
    moonraker_reachable: bool
    moonraker_info: dict[str, Any] | None
    artifacts: list[ArtifactInput]
    notes: list[str] = field(default_factory=list)
    normalized_artifacts: list[CollectedArtifact] = field(default_factory=list)
    observed_at: str = field(default_factory=utc_now)
    _inputs: tuple[tuple[str, str, str], ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.normalized_artifacts:
            self.normalized_artifacts = [
                normalize_input(item, origin="unknown", observed_at=self.observed_at)
                for item in self.artifacts
            ]
        self._inputs = tuple((item.kind, item.label, item.content) for item in self.artifacts)

    def refresh_artifacts(self) -> None:
        inputs = tuple((item.kind, item.label, item.content) for item in self.artifacts)
        if inputs != self._inputs:
            origins = {(item.kind, item.label): item.origin for item in self.normalized_artifacts}
            self.normalized_artifacts = [
                normalize_input(
                    item,
                    origin=origins.get((item.kind, item.label), "unknown"),
                    observed_at=self.observed_at,
                )
                for item in self.artifacts
            ]
            self._inputs = inputs

    def to_state(self) -> dict[str, Any]:
        self.refresh_artifacts()
        return {
            "moonraker_reachable": self.moonraker_reachable,
            "moonraker_info": self.moonraker_info,
            "artifacts": [item.model_dump() for item in self.artifacts],
            "notes": self.notes,
            "normalized_artifacts": [item.model_dump() for item in self.normalized_artifacts],
            "observed_at": self.observed_at,
        }

    @classmethod
    def from_state(cls, data: dict[str, Any]) -> DiagnosticsSnapshot:
        return cls(
            bool(data.get("moonraker_reachable", False)),
            data.get("moonraker_info"),
            [ArtifactInput.parse_obj(item) for item in data.get("artifacts", [])],
            list(data.get("notes", [])),
            [CollectedArtifact.parse_obj(item) for item in data.get("normalized_artifacts", [])],
            str(data.get("observed_at") or utc_now()),
        )

    def to_prompt_block(self) -> str:
        self.refresh_artifacts()
        sections: list[str] = []

        if self.moonraker_info:
            server = normalize_artifact(
                source="/server/info",
                content=self.moonraker_info,
                kind="printer_status",
                label="Moonraker server info",
                origin="moonraker",
                freshness="current_snapshot",
                observed_at=self.observed_at,
            )
            sections.append("Moonraker server info:\n" + json.dumps(server.prompt_value()))
        if self.notes:
            sections.append("Collector notes:\n" + "\n".join(self.notes))

        if self.artifacts:
            artifact_blocks = [
                json.dumps(artifact.prompt_value()) for artifact in self.normalized_artifacts
            ]
            sections.append("Artifacts:\n" + "\n\n".join(artifact_blocks))

        return "\n\n".join(sections) if sections else "No runtime context collected."
