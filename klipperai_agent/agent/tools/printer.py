from __future__ import annotations

from typing import Any

from pydantic import StrictBool

from klipperai_agent.agent.tools.base import Tool, ToolArguments, ToolContext
from klipperai_agent.diagnostics.evidence import config_evidence, diagnostic_evidence, link_findings
from klipperai_agent.domain.artifacts import CollectedArtifact
from klipperai_agent.domain.investigation import Evidence


def diagnostic_preview(content: str, limit: int = 1000) -> str:
    if len(content) <= limit:
        return content
    # Preserve selection metadata and the newest log evidence, not just the opening lines.
    return (
        content[:200]
        + "\n...[middle omitted; read artifact for more]...\n"
        + content[-(limit - 250) :]
    )


class PrinterProfileTool(Tool[ToolArguments]):
    name = "get_printer_profile"
    label = "Read saved printer profile"
    description = "Read saved firmware, board, probe and addon identity. This is saved configuration, not live state."
    arguments_type = ToolArguments

    async def execute(self, arguments: ToolArguments, context: ToolContext) -> dict[str, Any]:
        return context.services.profile.to_summary()


class PrinterStatusTool(Tool[ToolArguments]):
    name = "get_printer_status"
    label = "Check live printer status"
    description = "Read Moonraker printer state, temperatures and current print status without changing the printer."
    arguments_type = ToolArguments

    async def execute(self, arguments: ToolArguments, context: ToolContext) -> dict[str, Any]:
        info = await context.moonraker.get_printer_info()
        context.moonraker_reachable = True
        available = await context.moonraker.list_printer_objects()
        allowed = {"webhooks", "print_stats", "toolhead", "extruder", "heater_bed", "idle_timeout"}
        objects: dict[str, list[str] | None] = {name: None for name in available if name in allowed}
        status = await context.moonraker.query_printer_objects(objects) if objects else {}
        return {"printer_info": info, "status": status}


class DiagnosticsArguments(ToolArguments):
    include_logs: StrictBool = True
    include_system: StrictBool = False


class DiagnosticsTool(Tool[DiagnosticsArguments]):
    name = "collect_diagnostics"
    label = "Collect diagnostic evidence"
    description = "Read bounded host log tails and optionally service status/journal; run deterministic fault checks."
    arguments_type = DiagnosticsArguments

    async def execute(
        self, arguments: DiagnosticsArguments, context: ToolContext
    ) -> dict[str, Any]:
        snapshot = await context.diagnostics(arguments.include_logs, arguments.include_system)
        config = context.snapshots.get(False)
        context.moonraker_reachable = snapshot.moonraker_reachable
        context.findings = context.services.rules.analyze(
            snapshot.artifacts, config_snapshot=config
        )
        observations: list[CollectedArtifact] = [
            *diagnostic_evidence(snapshot),
            *(config_evidence(config) if config else []),
        ]
        context.findings = link_findings(context.findings, observations)
        known_ids = {item.id for item in context.evidence}
        context.evidence.extend(
            Evidence.parse_obj(item.model_dump())
            for item in observations
            if item.id not in known_ids
        )
        if not snapshot.artifacts:
            return {"error": "No diagnostic artifacts were available.", "notes": snapshot.notes}
        artifacts = []
        for artifact, observation in zip(
            snapshot.artifacts[:12], snapshot.normalized_artifacts[:12]
        ):
            identifier = f"diagnostic-{len(context.diagnostic_artifacts) + 1}"
            context.diagnostic_artifacts[identifier] = artifact
            artifacts.append(
                {
                    "id": identifier,
                    "label": artifact.label,
                    "kind": artifact.kind,
                    "content": diagnostic_preview(observation.content, 400),
                    "total_lines": len(artifact.content.splitlines()),
                    "artifact": observation.prompt_metadata(),
                    "evidence_id": observation.id,
                }
            )
        return {
            "truncated": len(snapshot.artifacts) > 12
            or any(len(artifact.content) > 400 for artifact in snapshot.artifacts),
            "moonraker_reachable": snapshot.moonraker_reachable,
            "notes": snapshot.notes[:20],
            "findings": [finding.model_dump() for finding in context.findings],
            "artifacts": artifacts,
            "omitted_artifacts": max(0, len(snapshot.artifacts) - len(artifacts)),
            "context_notes": "Bounded current log tails/service observations (not a guaranteed time window): "
            + "; ".join(
                artifact.label
                + " — "
                + next(
                    (
                        line
                        for line in artifact.content.splitlines()
                        if line.startswith("Selection:")
                    ),
                    "collected excerpt",
                )
                for artifact in snapshot.artifacts[:12]
            )
            + ". Use read_diagnostic_artifact to expand an excerpt. "
            + "; ".join(snapshot.notes[:10]),
        }
