from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from test_shutdown import START, stats

from klipperai_agent.infrastructure.host import shutdown_logs
from klipperai_agent.infrastructure.host.shutdown import ShutdownCollector, _current_fields
from klipperai_agent.infrastructure.host.system import CommandResult, SystemCommandRunner
from klipperai_agent.infrastructure.moonraker import MoonrakerClient, MoonrakerError


def test_log_discovery_reads_current_and_rotated_gzip_with_limits(tmp_path, monkeypatch):
    (tmp_path / "klippy.log").write_text("new healthy run")
    (tmp_path / "klippy.log.1").write_text("retained stop")
    (tmp_path / "klippy.log.2.gz").write_bytes(gzip.compress(b"earlier stop"))
    (tmp_path / "klippy.log.3").write_text("old stop")
    (tmp_path / "secret.cfg").write_text("private")
    (tmp_path / "klippy.log.secret").write_text("private")
    for index, name in enumerate(["klippy.log.1", "klippy.log.2.gz", "klippy.log.3"]):
        os.utime(tmp_path / name, (100 - index, 100 - index))
    logs = shutdown_logs.collect_shutdown_logs(tmp_path, ())
    assert [item.content for item in logs.excerpts] == [
        "new healthy run",
        "retained stop",
        "earlier stop",
    ]
    assert "older rotations omitted" in str(logs.notes)
    assert not shutdown_logs.collect_shutdown_logs(tmp_path, ("KLIPPY",)).excerpts
    assert not shutdown_logs.collect_shutdown_logs(tmp_path, ("klippy.log",)).excerpts
    assert "klippy.log.1" not in [
        item.source for item in shutdown_logs.collect_shutdown_logs(tmp_path, ("*.1",)).excerpts
    ]
    monkeypatch.setattr(shutdown_logs, "TAIL_BYTES", 30)
    monkeypatch.setattr(shutdown_logs, "INFLATE_BYTES", 100)
    (tmp_path / "klippy.log").write_text("x" * 100 + "\nTimer too close")
    (tmp_path / "klippy.log.1").write_text("x" * 100)  # no complete line in tail
    (tmp_path / "klippy.log.2.gz").write_bytes(gzip.compress(b"x" * 60 + b"\nTimer too close"))
    limited = shutdown_logs.collect_shutdown_logs(tmp_path, ())
    assert all(item.partial for item in limited.excerpts)
    assert limited.excerpts[0].content == "Timer too close"
    by_name = {item.source: item.content for item in limited.excerpts}
    assert by_name["klippy.log.1"] == ""
    assert by_name["klippy.log.2.gz"] == "Timer too close"
    (tmp_path / "klippy.log.2.gz").write_bytes(gzip.compress(b"x" * 101))
    assert "decompression budget" in str(shutdown_logs.collect_shutdown_logs(tmp_path, ()).notes)
    (tmp_path / "klippy.log.2.gz").write_bytes(b"x" * 101)
    assert "decompression budget" in str(shutdown_logs.collect_shutdown_logs(tmp_path, ()).notes)


def test_log_read_failures_are_partial_not_fatal(tmp_path, monkeypatch):
    assert "unavailable" in str(shutdown_logs.collect_shutdown_logs(tmp_path / "absent", ()).notes)
    assert "No eligible" in str(shutdown_logs.collect_shutdown_logs(tmp_path, ()).notes)
    (tmp_path / "klippy.log.gz").write_bytes(b"bad gzip")
    assert "corrupt" in str(shutdown_logs.collect_shutdown_logs(tmp_path, ()).notes)
    (tmp_path / "klippy.log.1").mkdir()
    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == "klippy.log.gz")
    assert not shutdown_logs.collect_shutdown_logs(tmp_path, ()).excerpts
    monkeypatch.setattr(Path, "is_symlink", lambda self: False)
    monkeypatch.setattr(shutdown_logs.os, "fstat", lambda fd: SimpleNamespace(st_mode=0))
    assert "unreadable" in str(shutdown_logs.collect_shutdown_logs(tmp_path, ()).notes)


def collector(tmp_path, *, data=None, runner=None, **kwargs):
    moonraker = SimpleNamespace(get_process_stats=AsyncMock(return_value=data or {}))
    return ShutdownCollector(
        moonraker, tmp_path, logs_enabled=True, journal_enabled=True, runner=runner, **kwargs
    )


def record(message, stamp=1792058402):
    return json.dumps(
        {
            "MESSAGE": message,
            "__REALTIME_TIMESTAMP": str(stamp * 1_000_000),
            "_BOOT_ID": "previous-boot",
        }
    )


def test_current_snapshot_bounds_fields_and_keeps_flags_unattributed():
    result = _current_fields(
        {
            "cpu_temp": 55.0,
            "system_uptime": 1234,
            "system_memory": {"total": 123456, "used": -1, "available": float("nan"), "secret": 42},
            "system_cpu_usage": {"cpu": 5, "cpu0": 3, "cpu100": 1, "injected": 10},
            "throttled_state": {"bits": 65536, "flags": ["Previously Under-Volted" * 20] * 12},
        }
    )
    assert result["cpu_temp"] == 55 and result["system_uptime"] == 1234
    assert result["system_memory"] == {"total": 123456}
    assert result["system_cpu_usage"] == {"cpu": 5, "cpu0": 3}
    assert len(result["throttled_state"]["flags"]) == 8
    assert len(result["throttled_state"]["flags"][0]) == 120
    assert _current_fields(
        {"cpu_temp": True, "system_cpu_usage": [], "throttled_state": {"bits": "bad", "flags": [1]}}
    ) == {"throttled_state": {"flags": []}}


@pytest.mark.asyncio
async def test_host_collects_only_fixed_endpoint_and_time_bounded_kernel_journal(tmp_path):
    requested = []

    def handler(request):
        requested.append((request.method, request.url.path))
        return httpx.Response(
            200,
            json={
                "result": {
                    "system_cpu_usage": {"cpu": 5},
                    "system_memory": {"available": 100000},
                    "throttled_state": {"bits": 65536, "flags": ["Previously Under-Volted"]},
                    "network": {"private": "value"},
                }
            },
        )

    client = MoonrakerClient("http://moonraker")
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://moonraker"
    )
    runner = Mock()
    runner.run.return_value = CommandResult((), 0, record("usb 1-1: USB disconnect"), "")
    reader = ShutdownCollector(
        client, tmp_path, logs_enabled=True, journal_enabled=True, runner=runner
    )
    (tmp_path / "klippy.log").write_text(
        START + "\n" + stats(102) + "\nLost communication with MCU 'mcu'"
    )
    assert (await reader.read_logs()).excerpts
    host = await reader.read_host(1792058402)
    assert requested == [("GET", "/machine/proc_stats")]
    assert "network" not in host.current and host.current["throttled_state"]["bits"] == 65536
    assert "NOT measurements" in host.current["scope"]
    assert len(host.kernel) == 1
    command = runner.run.call_args.args[0]
    assert "_TRANSPORT=kernel" in command and "-k" not in command and "--boot" not in command
    assert "@1792058312.000" in command and "@1792058412.000" in command
    await client.aclose()


@pytest.mark.asyncio
async def test_host_disabled_and_missing_clocks_never_query_journal(tmp_path):
    runner = Mock()
    reader = ShutdownCollector(
        SimpleNamespace(get_process_stats=AsyncMock(side_effect=MoonrakerError("secret"))),
        tmp_path,
        logs_enabled=False,
        journal_enabled=False,
        runner=runner,
    )
    assert "disabled" in str((await reader.read_logs()).notes)
    result = await reader.read_host(None)
    assert "unavailable" in str(result.notes) and "disabled" in str(result.notes)
    assert "secret" not in str(result)
    for stamp in (None, float("nan"), 5):
        result = await collector(tmp_path, runner=runner).read_host(stamp)
        assert "wall-clock" in str(result.notes)
    runner.run.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [OSError(), subprocess.TimeoutExpired("journalctl", 1)])
async def test_journal_failure_does_not_lose_current_readings(tmp_path, error):
    reader = collector(tmp_path, runner=SimpleNamespace(run=Mock(side_effect=error)))
    result = await reader.read_host(1792058402)
    assert result.current and not result.kernel and "unavailable" in str(result.notes)


@pytest.mark.asyncio
async def test_journal_permission_empty_malformed_and_truncated_records(tmp_path):
    runner = Mock()
    runner.run.return_value = CommandResult((), 1, "", "private error")
    reader = collector(tmp_path, runner=runner)
    assert "read failed" in str((await reader.read_host(1792058402)).notes)
    runner.run.return_value = CommandResult((), 0, "", "")
    assert "No readable" in str((await reader.read_host(1792058402)).notes)
    lines = [record("fine")] * 200 + ["bad JSON", "[]", record("too old", 1), record([1, 2])]
    runner.run.return_value = CommandResult((), 0, "\n".join(lines), "access warning", True)
    result = await reader.read_host(1792058402)
    assert len(result.kernel) == 196
    assert "byte limit" in str(result.notes)
    assert (
        "limit reached" in str(result.notes)
        and "Unusable" in str(result.notes)
        and "warning" in str(result.notes)
    )


def test_bounded_command_output_and_timeout_cleanup():
    runner = SystemCommandRunner(timeout_seconds=5)
    result = runner.run(
        (sys.executable, "-c", "import sys; print('x'*100); sys.stderr.write('y'*100)"),
        max_output_bytes=20,
    )
    assert result.stdout == "x" * 20 and result.stderr == "y" * 20 and result.truncated
    result = runner.run((sys.executable, "-c", "print('ok')"), max_output_bytes=20)
    assert result.stdout == "ok" and not result.truncated
    with pytest.raises(subprocess.TimeoutExpired):
        SystemCommandRunner(timeout_seconds=0.01).run(
            (sys.executable, "-c", "import time; time.sleep(10)"), max_output_bytes=20
        )
