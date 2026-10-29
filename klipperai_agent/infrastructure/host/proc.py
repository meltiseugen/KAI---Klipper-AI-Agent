"""Finite reads of fixed Linux proc files. Never reads cmdline, environ or user files."""

from __future__ import annotations

import os
import time
from pathlib import Path

from klipperai_agent.domain.host_history import HostSample, PressureSample, ProcessSample
from klipperai_agent.domain.redaction import redact_text

MAX_PROCESSES = 256
MAX_DIRECTORY_ENTRIES = 4096


def counters(text: str, allowed: set[str]) -> dict[str, int]:
    result = {}
    for line in text.splitlines():
        parts = line.replace(":", " ").split()
        if len(parts) >= 2 and parts[0] in allowed:
            value = int(parts[1])
            if value >= 0:
                result[parts[0]] = value
    return result


def pressure(text: str) -> PressureSample:
    values = {}
    for line in text.splitlines():
        parts = line.split()
        if not parts or parts[0] not in {"some", "full"}:
            continue
        fields = dict(part.split("=", 1) for part in parts[1:] if "=" in part)
        if "avg10" in fields:
            values[f"{parts[0]}_avg10"] = float(fields["avg10"])
        if "total" in fields:
            values[f"{parts[0]}_total_us"] = int(fields["total"])
    return PressureSample.parse_obj(values)


class ProcSampler:
    def __init__(self, root: Path = Path("/proc"), *, ticks: int = 100, page_kib: int = 4):
        self.root = root
        self.ticks = ticks
        self.page_kib = page_kib
        self.previous: tuple[float, float, list[int], dict[int, tuple[int, int]]] | None = None

    def _read(self, relative: str, limit: int = 65536) -> str:
        with (self.root / relative).open("rb") as source:
            data = source.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Proc read exceeded its byte bound.")
        return data.decode("utf-8", errors="replace")

    def sample(self) -> HostSample:
        stamp = time.time()
        uptime = float(self._read("uptime").split()[0])
        cpu = [int(value) for value in self._read("stat").splitlines()[0].split()[1:9]]
        if len(cpu) != 8 or min(cpu) < 0:
            raise ValueError("Invalid CPU counters.")
        sample = HostSample(unix_time=stamp, uptime_seconds=uptime)
        prior = self.previous
        interval = uptime - prior[1] if prior else 0
        if prior and interval > 0 and abs((stamp - prior[0]) - interval) <= 2:
            sample.interval_seconds = interval
            deltas = [new - old for new, old in zip(cpu, prior[2])]
            total = sum(deltas)
            if min(deltas) >= 0 and total > 0:
                sample.cpu_busy_percent = 100 * (total - deltas[3] - deltas[4]) / total
                sample.cpu_iowait_percent = 100 * deltas[4] / total
        else:
            prior = None
            sample.notes.append(
                "First sample, reboot or clock discontinuity; CPU rates unavailable."
            )
        for name, allowed, target in (
            (
                "meminfo",
                {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"},
                sample.memory_kib,
            ),
            ("vmstat", {"pswpin", "pswpout", "pgpgin", "pgpgout", "oom_kill"}, sample.vm_counters),
        ):
            try:
                target.update(counters(self._read(name), allowed))
            except (OSError, ValueError):
                sample.notes.append(f"{name} unavailable or malformed.")
        for resource in ("cpu", "memory", "io"):
            try:
                sample.pressure[resource] = pressure(self._read(f"pressure/{resource}"))
            except (OSError, ValueError):
                sample.notes.append(
                    f"{resource} pressure unavailable (kernel support/permissions)."
                )
        process_counters: dict[int, tuple[int, int]] = {}
        processes = []
        try:
            with os.scandir(self.root) as entries:
                for index, entry in enumerate(entries):
                    if index >= MAX_DIRECTORY_ENTRIES or len(process_counters) >= MAX_PROCESSES:
                        sample.notes.append(
                            "Process scan capped; unobserved workloads may be absent."
                        )
                        break
                    if not entry.name.isdecimal() or not entry.is_dir(follow_symlinks=False):
                        continue
                    # Count attempted processes too, including inaccessible/exited ones.
                    pid = int(entry.name)
                    process_counters[pid] = (0, 0)
                    try:
                        text = self._read(f"{pid}/stat", 4096)
                        end = text.rindex(")")
                        fields = text[end + 2 :].split()
                        cpu_ticks = int(fields[11]) + int(fields[12])
                        started, rss = int(fields[19]), int(fields[21])
                        if min(cpu_ticks, started, rss) < 0:
                            raise ValueError("Invalid process counters.")
                        process_counters[pid] = (started, cpu_ticks)
                        old = prior[3].get(pid) if prior else None
                        rate = None
                        if old and old[0] == started and cpu_ticks >= old[1]:
                            rate = 100 * (cpu_ticks - old[1]) / self.ticks / interval
                        processes.append(
                            ProcessSample(
                                pid=pid,
                                name=redact_text(text[text.index("(") + 1 : end])[:64],
                                cpu_percent_one_core=rate,
                                rss_kib=rss * self.page_kib,
                            )
                        )
                    except (OSError, ValueError, IndexError):
                        sample.notes.append(
                            "Some processes exited, were inaccessible or malformed."
                        )
        except OSError:
            sample.notes.append("Process directory unavailable.")
        # Retain both CPU-heavy and memory-heavy processes, at most eight total.
        top = sorted(processes, key=lambda item: item.cpu_percent_one_core or 0, reverse=True)[:4]
        top += sorted(processes, key=lambda item: item.rss_kib, reverse=True)[:4]
        sample.processes = list({item.pid: item for item in top}.values())
        sample.notes = list(dict.fromkeys(sample.notes))[:12]
        self.previous = (stamp, uptime, cpu, process_counters)
        return sample
