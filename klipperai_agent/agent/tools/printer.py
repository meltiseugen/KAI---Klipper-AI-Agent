from __future__ import annotations

from typing import Any

from pydantic import StrictBool

from klipperai_agent.agent.tools.base import Tool, ToolArguments, ToolContext


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
        snapshot = await context.services.collector.collect(
            context.artifacts,
            include_host_logs=arguments.include_logs,
            include_host_system=arguments.include_system,
        )
        config = await context.config()
        context.moonraker_reachable = snapshot.moonraker_reachable
        context.findings = context.services.rules.analyze(
            snapshot.artifacts, config_snapshot=config
        )
        return {
            "moonraker_reachable": snapshot.moonraker_reachable,
            "notes": snapshot.notes,
            "findings": [finding.model_dump() for finding in context.findings],
            "artifacts": [
                {
                    "label": artifact.label,
                    "kind": artifact.kind,
                    "content": artifact.prompt_excerpt(5000),
                }
                for artifact in snapshot.artifacts
            ],
        }
