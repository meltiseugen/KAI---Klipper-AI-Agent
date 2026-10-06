from __future__ import annotations

import pytest

from klipperai_agent.contracts.api import ArtifactInput
from klipperai_agent.diagnostics.collector import DiagnosticsCollector
from klipperai_agent.diagnostics.models import DiagnosticsSnapshot
from klipperai_agent.diagnostics.rules import RuleEngine
from klipperai_agent.infrastructure.moonraker import MoonrakerError


def test_diagnostics_snapshot_prompt_rendering() -> None:
    assert DiagnosticsSnapshot(False, None, []).to_prompt_block() == "No runtime context collected."
    snapshot = DiagnosticsSnapshot(
        True,
        {"state": "ready"},
        [ArtifactInput(label="note", content="body")],
        ["collected"],
    )
    rendered = snapshot.to_prompt_block()
    assert "Moonraker server info" in rendered
    assert "Collector notes" in rendered
    assert "Artifacts" in rendered


@pytest.mark.asyncio
async def test_diagnostics_collector_failure_ping_and_system_context() -> None:
    class Moonraker:
        async def ping(self):
            return False

        async def get_server_info(self):
            raise MoonrakerError("offline")

    class System:
        def collect(self):
            return [ArtifactInput(kind="system_log", label="status", content="ok")], ["system note"]

    collector = DiagnosticsCollector(Moonraker(), host_system=System())
    assert await collector.ping() is False
    snapshot = await collector.collect([])
    assert snapshot.moonraker_reachable is False
    assert snapshot.notes == ["offline", "system note"]
    assert snapshot.artifacts[0].label == "status"


@pytest.mark.asyncio
async def test_diagnostics_collector_checks_printer_reachability() -> None:
    class Moonraker:
        def __init__(self, fail: bool) -> None:
            self.fail = fail

        async def get_printer_info(self):
            if self.fail:
                raise MoonrakerError("offline")
            return {"state": "ready"}

    assert await DiagnosticsCollector(Moonraker(False)).ping_printer() is True
    assert await DiagnosticsCollector(Moonraker(True)).ping_printer() is False


def test_rule_engine_deduplicates_and_ranks_unknown_severity() -> None:
    artifacts = [
        ArtifactInput(label="same", content="Timer too close"),
        ArtifactInput(label="same", content="Timer too close"),
    ]
    findings = RuleEngine().analyze(artifacts)
    assert len(findings) == 1
    assert RuleEngine._severity_rank("unknown") == 0
