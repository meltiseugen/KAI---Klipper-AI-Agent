from __future__ import annotations

import subprocess
from types import SimpleNamespace

from klipperai_agent.infrastructure.host.system import (
    CommandResult,
    HostSystemCollector,
)


class _FakeRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: tuple[str, ...]) -> CommandResult:
        self.commands.append(command)
        unit_name = command[command.index("--unit") + 1] if "--unit" in command else command[-1]

        if command[0] == "systemctl":
            return CommandResult(
                command=command,
                returncode=0,
                stdout=(
                    f"Id={unit_name}\n"
                    "LoadState=loaded\n"
                    "ActiveState=active\n"
                    "SubState=running\n"
                    "Result=success"
                ),
                stderr="",
            )

        return CommandResult(
            command=command,
            returncode=0,
            stdout=f"2026-05-18T10:11:12+00:00 host {unit_name}[123]: started cleanly",
            stderr="",
        )


class _FailingRunner:
    def run(self, command: tuple[str, ...]) -> CommandResult:
        if command[0] == "systemctl":
            raise FileNotFoundError("systemctl")
        raise subprocess.TimeoutExpired(command, 3)


def test_host_system_collector_collects_service_status_and_journal() -> None:
    runner = _FakeRunner()
    collector = HostSystemCollector(
        moonraker_service_name="moonraker.service",
        klipper_service_name="klipper.service",
        journal_lines=25,
        runner=runner,
    )

    artifacts, notes = collector.collect()

    assert len(artifacts) == 4
    assert any(artifact.label == "systemctl show moonraker.service" for artifact in artifacts)
    assert any(artifact.label == "journalctl moonraker.service" for artifact in artifacts)
    assert any("Collected systemctl status for moonraker.service." == note for note in notes)
    assert any("Collected the last 25 journal lines for klipper.service." == note for note in notes)
    assert runner.commands[0][0] == "systemctl"
    assert runner.commands[1][0] == "journalctl"


def test_host_system_collector_reports_missing_commands_and_timeouts() -> None:
    collector = HostSystemCollector(runner=_FailingRunner())
    artifacts, notes = collector.collect()

    assert artifacts == []
    assert any("systemctl is not available on this host." == note for note in notes)
    assert any(
        "Timed out while collecting journalctl output for moonraker.service." == note
        for note in notes
    )


def test_system_command_runner_captures_and_strips_output(monkeypatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=7, stdout=" out \n", stderr=" err \n"),
    )
    runner = __import__(
        "klipperai_agent.infrastructure.host.system", fromlist=["SystemCommandRunner"]
    ).SystemCommandRunner(2.5)
    result = runner.run(("test", "arg"))
    assert result.returncode == 7
    assert result.stdout == "out"
    assert result.stderr == "err"


class _EdgeRunner:
    def __init__(self, result: CommandResult) -> None:
        self.result = result

    def run(self, command: tuple[str, ...]) -> CommandResult:
        return CommandResult(
            command, self.result.returncode, self.result.stdout, self.result.stderr
        )


def test_host_system_collector_reports_failed_and_empty_commands() -> None:
    failed = HostSystemCollector(runner=_EdgeRunner(CommandResult((), 1, "stdout failure", "")))
    artifacts, notes = failed.collect()
    assert artifacts == []
    assert any("systemctl show failed" in note for note in notes)
    assert any("journalctl failed" in note for note in notes)

    empty = HostSystemCollector(runner=_EdgeRunner(CommandResult((), 0, "", "")))
    artifacts, notes = empty.collect()
    assert artifacts == []
    assert any("returned no data" in note for note in notes)
    assert any("returned no lines" in note for note in notes)


def test_host_system_collector_handles_remaining_errors_and_clipping() -> None:
    class Runner:
        def run(self, command: tuple[str, ...]) -> CommandResult:
            if command[0] == "systemctl":
                raise subprocess.TimeoutExpired(command, 1)
            raise FileNotFoundError("journalctl")

    artifacts, notes = HostSystemCollector(runner=Runner()).collect()
    assert artifacts == []
    assert any("Timed out while collecting systemctl" in note for note in notes)
    assert "journalctl is not available on this host." in notes

    text = HostSystemCollector._clip_text("a" * 100, 80, 50)
    assert "...[truncated]..." in text
    items = ["same"]
    HostSystemCollector._append_unique(items, "same")
    assert items == ["same"]
