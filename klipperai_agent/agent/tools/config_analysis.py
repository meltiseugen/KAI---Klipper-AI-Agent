from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

from klipperai_agent.agent.ports import ConfigReader
from klipperai_agent.agent.tools.base import Tool, ToolArguments, ToolContext
from klipperai_agent.config.analysis import analyze_config
from klipperai_agent.config.models import ConfigReadError, ConfigSnapshot
from klipperai_agent.diagnostics.evidence import config_evidence, link_findings
from klipperai_agent.domain.artifacts import CollectedArtifact
from klipperai_agent.domain.config_analysis import ConfigAnalysis
from klipperai_agent.domain.investigation import Evidence


async def collect_analysis(configs: ConfigReader, snapshot: ConfigSnapshot) -> ConfigAnalysis:
    documents = []
    size = 0
    notes = list(snapshot.notes)
    for doc in snapshot.documents:
        try:
            full = (
                await asyncio.to_thread(configs.read_collected_document, doc)
                if doc.truncated
                else doc
            )
            size += len(full.content)
            if size > 2_000_000:
                raise ConfigReadError("Configuration analysis exceeds the full-read budget.")
            documents.append(full)
        except (ConfigReadError, OSError):
            notes.append(
                "Full active configuration could not be read within the analysis budget; refresh evidence and retry."
            )
            break
    return analyze_config(replace(snapshot, documents=documents, notes=notes))


class AnalyzeConfigTool(Tool[ToolArguments]):
    name = "analyze_config"
    label = "Analyze active printer configuration"
    description = "Read-only static analysis of active on-disk includes, section conflicts and pin references. No arguments or firmware execution."
    arguments_type = ToolArguments

    async def execute(self, arguments: ToolArguments, context: ToolContext) -> dict[str, Any]:
        snapshot = await context.config()
        report = await collect_analysis(context.services.config_collector, snapshot)
        observations: list[CollectedArtifact] = list(config_evidence(snapshot))
        report.findings = link_findings(report.findings, observations)
        known_ids = {item.id for item in context.evidence}
        context.evidence.extend(
            Evidence.parse_obj(item.model_dump())
            for item in observations
            if item.id not in known_ids
        )
        context.findings.extend(report.findings)
        context.citations.extend(report.citations)
        return {
            **report.model_dump(),
            "truncated": not report.complete,
            "context_notes": "Active on-disk configuration; static checks only.",
        }
