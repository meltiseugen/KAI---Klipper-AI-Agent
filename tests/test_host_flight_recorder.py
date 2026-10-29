from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from klipperai_agent.diagnostics.host_history import summarize_history
from klipperai_agent.domain.host_history import HostSample, PressureSample
from klipperai_agent.infrastructure.host import flight_recorder, history_store, proc
from klipperai_agent.infrastructure.host.flight_recorder import HostFlightRecorder
from klipperai_agent.infrastructure.host.history_store import HostHistoryStore
from klipperai_agent.infrastructure.host.proc import ProcSampler, counters, pressure
from klipperai_agent.infrastructure.host.shutdown import ShutdownCollector

STAMP = 1792058402


def sample(stamp=STAMP, **kwargs):
    return HostSample(unix_time=stamp, uptime_seconds=100, **kwargs)


def write_proc(
    root, *, uptime=100, busy=100, idle=100, pid=12, ticks=100, started=1, name="worker (a)"
):
    root.mkdir(exist_ok=True)
    (root / "uptime").write_text(f"{uptime} 0")
    (root / "stat").write_text(f"cpu {busy} 0 0 {idle} 0 0 0 0 0 0\n")
    (root / "meminfo").write_text(
        "MemTotal: 1024 kB\nMemAvailable: 500 kB\nSwapTotal: 20 kB\nSwapFree: 10 kB\nSecret: 9\n"
    )
    (root / "vmstat").write_text("pswpin 5\npswpout 10\npgpgin 100\npgpgout 200\noom_kill 0\n")
    (root / "pressure").mkdir(exist_ok=True)
    for resource in ("cpu", "memory", "io"):
        (root / f"pressure/{resource}").write_text(
            "some avg10=10.00 avg60=2 total=123\nfull avg10=1.00 total=10\n"
        )
    (root / str(pid)).mkdir(exist_ok=True)
    fields = ["0"] * 22
    fields[0], fields[11], fields[19], fields[21] = "S", str(ticks), str(started), "30"
    (root / str(pid) / "stat").write_text(f"{pid} ({name}) " + " ".join(fields))


def test_proc_rates_units_pid_reuse_and_clock_discontinuity(tmp_path, monkeypatch):
    clock = [STAMP]
    monkeypatch.setattr(proc.time, "time", lambda: clock[0])
    write_proc(tmp_path)
    sampler = ProcSampler(tmp_path)
    first = sampler.sample()
    assert first.cpu_busy_percent is None and first.processes[0].cpu_percent_one_core is None
    assert first.memory_kib["MemAvailable"] == 500 and "Secret" not in first.memory_kib
    assert first.vm_counters["pswpout"] == 10
    assert first.pressure["io"].some_avg10 == 10
    assert first.processes[0].name == "worker (a)" and first.processes[0].rss_kib == 120
    clock[0] += 10
    write_proc(tmp_path, uptime=110, busy=190, idle=110, ticks=600)
    second = sampler.sample()
    assert second.cpu_busy_percent == 90 and second.cpu_iowait_percent == 0
    assert second.processes[0].cpu_percent_one_core == 50
    clock[0] += 10
    write_proc(tmp_path, uptime=120, busy=200, idle=120, started=2)
    assert sampler.sample().processes[0].cpu_percent_one_core is None
    clock[0] += 100
    write_proc(tmp_path, uptime=130)
    assert sampler.sample().interval_seconds is None
    assert counters("x -1\ny 4\nz", {"x", "y"}) == {"y": 4}
    assert pressure("\nignored total=0\nsome total=2").some_total_us == 2
    with pytest.raises(ValueError):
        pressure("some avg10=nan")


def test_proc_missing_malformed_and_scan_bounds(tmp_path, monkeypatch):
    write_proc(tmp_path)
    sampler = ProcSampler(tmp_path)
    with pytest.raises(ValueError, match="byte bound"):
        sampler._read("stat", 1)
    (tmp_path / "stat").write_text("cpu 1 2\n")
    with pytest.raises(ValueError, match="CPU"):
        sampler.sample()
    write_proc(tmp_path)
    (tmp_path / "12/stat").write_text("bad")
    (tmp_path / "meminfo").write_text("MemTotal: malformed")
    (tmp_path / "pressure/io").unlink()
    result = sampler.sample()
    assert not result.processes
    assert "malformed" in str(result.notes) and "pressure unavailable" in str(result.notes)
    write_proc(tmp_path)
    monkeypatch.setattr(proc, "MAX_PROCESSES", 0)
    assert "scan capped" in str(sampler.sample().notes)
    monkeypatch.setattr(proc.os, "scandir", Mock(side_effect=OSError()))
    assert "directory unavailable" in str(sampler.sample().notes)


def test_proc_top_processes_and_counter_reset(tmp_path, monkeypatch):
    clock = [STAMP]
    monkeypatch.setattr(proc.time, "time", lambda: clock[0])
    for pid in range(1, 15):
        write_proc(tmp_path, pid=pid, ticks=pid * 100)
    sampler = ProcSampler(tmp_path)
    assert len(sampler.sample().processes) <= 8
    clock[0] += 10
    write_proc(tmp_path, uptime=110, busy=0, idle=0, pid=1, ticks=0)
    assert sampler.sample().cpu_busy_percent is None
    write_proc(tmp_path, pid=1, ticks=-1)
    assert "malformed" in str(sampler.sample().notes)


def test_store_retention_restart_window_and_private_paths(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="retention"):
        HostHistoryStore(tmp_path, (), 1)
    with pytest.raises(ValueError, match="outside printer"):
        HostHistoryStore(tmp_path, (tmp_path,), 12)
    store = HostHistoryStore(tmp_path, (), 12)
    for offset in range(20):
        store.append(sample(STAMP + offset))
    restarted = HostHistoryStore(tmp_path, (), 12)
    assert len(restarted.window(STAMP + 10)) == 12
    assert restarted.window(STAMP + 10)[0].unix_time == STAMP + 8
    assert restarted.window(STAMP - 1000) == []
    with closing(sqlite3.connect(store.path)) as db:
        assert (
            db.execute("PRAGMA page_count").fetchone()[0] * 4096 < history_store.MAX_DATABASE_BYTES
        )
    monkeypatch.setattr(history_store, "MAX_PAYLOAD_BYTES", len(sample().json()) * 2 + 10)
    store.append(sample())
    assert len(store.window(STAMP)) <= 2
    old_limit = history_store.MAX_DATABASE_BYTES
    monkeypatch.setattr(history_store, "MAX_DATABASE_BYTES", store.path.stat().st_size - 1)
    with pytest.raises(ValueError, match="database exceeds"):
        store.window(STAMP)
    monkeypatch.setattr(history_store, "MAX_DATABASE_BYTES", old_limit)
    monkeypatch.setattr(history_store, "MAX_SAMPLE_BYTES", 1)
    with pytest.raises(ValueError, match="storage bound"):
        store.append(sample())
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == store.path.parent)
    with pytest.raises(ValueError, match="private"):
        store.window(STAMP)


def test_history_pre_stop_only_and_bounded_excerpts():
    records = [
        sample(
            STAMP - i,
            cpu_busy_percent=50,
            memory_kib={"MemAvailable": 500},
            pressure={"io": PressureSample(some_avg10=25)},
        )
        for i in range(10)
    ]
    records.append(sample(STAMP + 1, cpu_busy_percent=100))
    result = summarize_history(records, STAMP)
    assert result["sample_count"] == 11 and len(result["samples"]) == 6 and result["truncated"]
    assert result["pre_stop_summary"]["max_cpu_busy_percent"]["value"] == 50
    assert "No retained pre-stop" in str(summarize_history([], STAMP))


@pytest.mark.asyncio
async def test_recorder_lifecycle_retry_and_shutdown_handoff(tmp_path, monkeypatch):
    store = HostHistoryStore(tmp_path, (), 12)
    recorder = HostFlightRecorder(store, 0.001)
    monkeypatch.setattr(flight_recorder.sys, "platform", "linux")
    monkeypatch.setattr(
        flight_recorder.os,
        "sysconf",
        lambda name: 100 if name == "SC_CLK_TCK" else 4096,
        raising=False,
    )
    ready = asyncio.Event()
    counter = [0]

    loop = asyncio.get_running_loop()

    def successful():
        counter[0] += 1
        if counter[0] == 1:
            raise OSError()
        store.append(sample())
        loop.call_soon_threadsafe(ready.set)

    monkeypatch.setattr(recorder, "_record", successful)
    recorder.start()
    recorder.start()
    await asyncio.wait_for(ready.wait(), 2)
    await recorder.aclose()
    assert counter[0] >= 2 and recorder.error is None and recorder._task is None
    assert recorder.read_window(STAMP)["sample_count"] >= 1
    for stamp in (None, float("nan"), 0):
        assert "clock anchor" in str(recorder.read_window(stamp))
    recorder.error = "sample failure"
    assert "sample failure" in str(recorder.read_window(STAMP))
    collector = ShutdownCollector(
        SimpleNamespace(get_process_stats=AsyncMock(return_value={})),
        tmp_path,
        logs_enabled=False,
        journal_enabled=False,
        history=recorder,
    )
    host = await collector.read_host(STAMP)
    assert host.history["sample_count"] >= 1 and not host.kernel
    monkeypatch.setattr(store, "window", Mock(side_effect=sqlite3.DatabaseError()))
    assert "unavailable" in str(recorder.read_window(STAMP))
    monkeypatch.setattr(flight_recorder.sys, "platform", "win32")
    recorder.start()
    assert "requires Linux" in recorder.error
    await recorder.aclose()


def test_recorder_record_uses_sampler_and_does_not_store_private_process_details(tmp_path):
    recorder = HostFlightRecorder(HostHistoryStore(tmp_path / "data", (), 12))
    root = tmp_path / "proc"
    write_proc(root)
    recorder.sampler = ProcSampler(root)
    recorder._record()
    with closing(sqlite3.connect(recorder.store.path)) as db:
        content = db.execute("SELECT content FROM samples").fetchone()[0]
        assert "cmdline" not in content and "environ" not in content
        assert json.loads(content)["processes"][0]["name"] == "worker (a)"
