"""Read-only capabilities needed by tools; no provider, HTTP or workflow dependencies."""

from __future__ import annotations

from typing import Any, Protocol

from klipperai_agent.config.models import ConfigSnapshot
from klipperai_agent.diagnostics.models import DiagnosticsSnapshot
from klipperai_agent.domain.evidence import ArtifactInput, IssueFinding


class ConfigReader(Protocol):
    def collect_with_options(
        self, *, include_unincluded_configs: bool = False
    ) -> ConfigSnapshot: ...


class DiagnosticReader(Protocol):
    async def collect(
        self,
        artifacts: list[ArtifactInput],
        *,
        include_host_logs: bool = True,
        include_host_system: bool = True,
    ) -> DiagnosticsSnapshot: ...


class FindingRules(Protocol):
    def analyze(
        self, artifacts: list[ArtifactInput], *, config_snapshot: ConfigSnapshot | None = None
    ) -> list[IssueFinding]: ...


class SavedProfile(Protocol):
    def to_summary(self) -> dict[str, Any]: ...


class PrinterReader(Protocol):
    async def get_printer_info(self) -> dict[str, Any]: ...
    async def list_printer_objects(self) -> list[str]: ...
    async def query_printer_objects(
        self, objects: dict[str, list[str] | None]
    ) -> dict[str, Any]: ...


class ToolServices(Protocol):
    @property
    def collector(self) -> DiagnosticReader: ...
    @property
    def rules(self) -> FindingRules: ...
    @property
    def config_collector(self) -> ConfigReader: ...
    @property
    def profile(self) -> SavedProfile: ...
