from __future__ import annotations

import asyncio
from typing import Any

from klipperai_agent.diagnostics.models import DiagnosticsSnapshot
from klipperai_agent.domain.evidence import ArtifactInput
from klipperai_agent.infrastructure.host.logs import HostLogCollector
from klipperai_agent.infrastructure.host.system import HostSystemCollector
from klipperai_agent.infrastructure.moonraker import MoonrakerClient, MoonrakerError


class DiagnosticsCollector:
    def __init__(
        self,
        moonraker: MoonrakerClient,
        *,
        host_logs: HostLogCollector | None = None,
        host_system: HostSystemCollector | None = None,
    ) -> None:
        self._moonraker = moonraker
        self._host_logs = host_logs
        self._host_system = host_system

    async def ping(self) -> bool:
        return await self._moonraker.ping()

    async def ping_printer(self) -> bool:
        try:
            await self._moonraker.get_printer_info()
        except MoonrakerError:
            return False
        return True

    async def collect(
        self,
        artifacts: list[ArtifactInput],
        *,
        include_host_logs: bool = True,
        include_host_system: bool = True,
    ) -> DiagnosticsSnapshot:
        notes: list[str] = []
        moonraker_info: dict[str, Any] | None = None
        reachable = False
        snapshot_artifacts = list(artifacts)

        try:
            moonraker_info = await self._moonraker.get_server_info()
            reachable = True
        except MoonrakerError as exc:
            notes.append(str(exc))

        if include_host_logs and self._host_logs is not None:
            host_artifacts, host_notes = await asyncio.to_thread(self._host_logs.collect)
            snapshot_artifacts.extend(host_artifacts)
            notes.extend(host_notes)

        if include_host_system and self._host_system is not None:
            system_artifacts, system_notes = await asyncio.to_thread(self._host_system.collect)
            snapshot_artifacts.extend(system_artifacts)
            notes.extend(system_notes)

        return DiagnosticsSnapshot(
            moonraker_reachable=reachable,
            moonraker_info=moonraker_info,
            artifacts=snapshot_artifacts,
            notes=notes,
        )
