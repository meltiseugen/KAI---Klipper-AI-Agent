from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from klipperai_agent.agent.ports import PrinterReader, ToolServices
from klipperai_agent.config.models import ConfigDocument, ConfigReadError, ConfigSnapshot
from klipperai_agent.diagnostics.models import DiagnosticsSnapshot
from klipperai_agent.domain.base import BaseModel
from klipperai_agent.domain.context import ContextItem
from klipperai_agent.domain.evidence import ArtifactInput, IssueFinding, SourceCitation
from klipperai_agent.domain.investigation import Evidence
from klipperai_agent.domain.logs import LogInventory, LogWindow


class ToolArguments(BaseModel):
    class Config:
        extra = "forbid"


Arguments = TypeVar("Arguments", bound=ToolArguments)


@dataclass
class ToolContext:
    """Evidence belongs to one request, never to a shared singleton tool."""

    services: ToolServices
    moonraker: PrinterReader
    artifacts: list[ArtifactInput]
    findings: list[IssueFinding] = field(default_factory=list)
    citations: list[SourceCitation] = field(default_factory=list)
    moonraker_reachable: bool | None = None
    evidence: list[Evidence] = field(default_factory=list)
    snapshots: dict[bool, ConfigSnapshot] = field(default_factory=dict)
    context_included: list[ContextItem] = field(default_factory=list)
    diagnostic_snapshots: dict[tuple[bool, bool], DiagnosticsSnapshot] = field(default_factory=dict)
    diagnostic_artifacts: dict[str, ArtifactInput] = field(default_factory=dict)
    expanded_documents: dict[tuple[bool, str], ConfigDocument] = field(default_factory=dict)
    log_inventory: LogInventory | None = None
    log_windows: dict[str, LogWindow] = field(default_factory=dict)
    log_bytes_reserved: int = 0

    async def document(self, path: str, include_unincluded: bool = False) -> ConfigDocument | None:
        snapshot = await self.config(include_unincluded)
        document = next((doc for doc in snapshot.documents if doc.path == path), None)
        if document is None or not document.truncated:
            return document
        key = (include_unincluded, path)
        if key not in self.expanded_documents:
            expanded = await asyncio.to_thread(
                self.services.config_collector.read_collected_document, document
            )
            if (
                sum(len(item.content) for item in self.expanded_documents.values())
                + len(expanded.content)
                > 4_000_000
            ):
                raise ConfigReadError(
                    "Expanded config evidence budget reached. Narrow the files or start a new investigation."
                )
            self.expanded_documents[key] = expanded
        return self.expanded_documents[key]

    async def diagnostics(self, logs: bool, system: bool) -> DiagnosticsSnapshot:
        key = (logs, system)
        if key not in self.diagnostic_snapshots:
            snapshot = await self.services.collector.collect(
                self.artifacts, include_host_logs=logs, include_host_system=system
            )
            if not snapshot.artifacts:
                return snapshot  # Missing evidence can be retried during this request.
            self.diagnostic_snapshots[key] = snapshot
        return self.diagnostic_snapshots[key]

    async def config(self, include_unincluded: bool = False) -> ConfigSnapshot:
        if include_unincluded and False not in self.snapshots:
            await self.config(False)
        if include_unincluded not in self.snapshots:
            self.snapshots[include_unincluded] = await asyncio.to_thread(
                self.services.config_collector.collect_with_options,
                include_unincluded_configs=include_unincluded,
            )
        return self.snapshots[include_unincluded]


class Tool(ABC, Generic[Arguments]):
    name: str
    description: str
    label: str
    arguments_type: type[Arguments]

    def definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.arguments_type.schema(),
            # Pydantic validation is authoritative; optional arguments are allowed.
            "strict": False,
        }

    @abstractmethod
    async def execute(self, arguments: Arguments, context: ToolContext) -> dict[str, Any]: ...
