from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from klipperai_agent.agent.ports import PrinterReader, ToolServices
from klipperai_agent.config.models import ConfigSnapshot
from klipperai_agent.domain.base import BaseModel
from klipperai_agent.domain.evidence import ArtifactInput, IssueFinding, SourceCitation
from klipperai_agent.domain.investigation import Evidence


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
