"""Finite, read-only shutdown evidence collection. No model-controlled paths or commands."""

from __future__ import annotations

import asyncio
import json
import math
import re
import subprocess
from pathlib import Path

from klipperai_agent.domain.investigation import utc_now
from klipperai_agent.domain.shutdown import HostObservation, ShutdownLogs
from klipperai_agent.infrastructure.host.flight_recorder import HostFlightRecorder
from klipperai_agent.infrastructure.host.shutdown_logs import collect_shutdown_logs
from klipperai_agent.infrastructure.host.system import SystemCommandRunner
from klipperai_agent.infrastructure.moonraker import MoonrakerClient, MoonrakerError


def _current_fields(data: dict) -> dict:
    def number(value: object) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value >= 0
        )

    result: dict = {}
    for key in ("cpu_temp", "system_uptime"):
        if number(data.get(key)):
            result[key] = data[key]
    for key, allowed in (
        ("system_cpu_usage", r"cpu(?:[0-9]{1,2})?"),
        ("system_memory", r"total|available|used"),
    ):
        values = data.get(key)
        if isinstance(values, dict):
            result[key] = {
                name: value
                for name, value in values.items()
                if re.fullmatch(allowed, str(name)) and number(value)
            }
    throttled = data.get("throttled_state")
    if isinstance(throttled, dict):
        result["throttled_state"] = {}
        if number(throttled.get("bits")):
            result["throttled_state"]["bits"] = throttled["bits"]
        flags = throttled.get("flags")
        if isinstance(flags, list):
            result["throttled_state"]["flags"] = [
                item[:120] for item in flags[:8] if isinstance(item, str)
            ]
    return result


class ShutdownCollector:
    def __init__(
        self,
        moonraker: MoonrakerClient,
        logs_dir: Path,
        *,
        logs_enabled: bool,
        journal_enabled: bool,
        excluded_logs: tuple[str, ...] = (),
        runner: SystemCommandRunner | None = None,
        history: HostFlightRecorder | None = None,
    ) -> None:
        self._moonraker = moonraker
        self._logs_dir = logs_dir
        self._logs_enabled = logs_enabled
        self._journal_enabled = journal_enabled
        self._excluded = excluded_logs
        self._runner = runner or SystemCommandRunner()
        self._history = history

    async def read_logs(self) -> ShutdownLogs:
        if not self._logs_enabled:
            return ShutdownLogs(notes=["Host log collection disabled."])
        return await asyncio.to_thread(collect_shutdown_logs, self._logs_dir, self._excluded)

    async def read_host(self, estimated_unix_time: float | None) -> HostObservation:
        result = HostObservation()
        if self._history is not None:
            result.history = await asyncio.to_thread(self._history.read_window, estimated_unix_time)
        else:
            result.notes.append(
                "Host flight recorder disabled; no recorded process/pressure history available."
            )
        try:
            data = await self._moonraker.get_process_stats()
            # Explicit fields only; omit network addresses, identifiers and connection metadata.
            result.current = {
                "observed_at": utc_now(),
                "scope": "Current readings, NOT measurements at the shutdown. Historical throttle flags have no incident timestamp.",
                **_current_fields(data),
            }
        except (MoonrakerError, ValueError, TypeError, OverflowError):
            result.notes.append("Current host statistics unavailable from Moonraker.")
        if not self._journal_enabled:
            result.notes.append("Kernel journal collection disabled with system diagnostics.")
        elif (
            estimated_unix_time is None
            or not math.isfinite(estimated_unix_time)
            or not 946684800 <= estimated_unix_time <= 4102444800
        ):
            result.notes.append(
                "No usable incident wall-clock anchor; kernel events cannot be time-correlated."
            )
        else:
            result.kernel, notes = await asyncio.to_thread(self._kernel, estimated_unix_time)
            result.notes.extend(notes)
        return result

    def _kernel(self, stamp: float) -> tuple[list[dict], list[str]]:
        # _TRANSPORT searches retained boots, unlike -k which implies the current boot.
        command = (
            "journalctl",
            "_TRANSPORT=kernel",
            "--no-pager",
            "--output=json",
            "--output-fields=MESSAGE,__REALTIME_TIMESTAMP",
            "--since",
            f"@{stamp - 90:.3f}",
            "--until",
            f"@{stamp + 10:.3f}",
            "-n",
            "200",
        )
        try:
            result = self._runner.run(command, max_output_bytes=262144)
        except (OSError, subprocess.TimeoutExpired):
            return [], [
                "Kernel journal unavailable or timed out; permissions and retention may limit evidence."
            ]
        if result.returncode:
            return [], ["Kernel journal read failed; no conclusion about host health is possible."]
        notes = [
            "Kernel window: estimated incident time minus 90s to plus 10s; at most 200 records. Clock changes can invalidate correlation."
        ]
        if result.stderr:
            notes.append("journalctl reported a warning; journal access may be incomplete.")
        if result.truncated:
            notes.append("Kernel output byte limit reached; records may be incomplete.")
        events: list[dict] = []
        lines = result.stdout.splitlines()
        if len(lines) >= 200:
            notes.append("Kernel journal limit reached; earlier records may be missing.")
        for line in lines[-200:]:
            try:
                item = json.loads(line)
                timestamp = float(item["__REALTIME_TIMESTAMP"]) / 1_000_000
                message = item["MESSAGE"]
                if not isinstance(message, str) or not stamp - 90 <= timestamp <= stamp + 10:
                    continue
            except (ValueError, KeyError, TypeError, OverflowError):
                notes.append("Unusable kernel journal record omitted.")
                continue
            events.append({"unix_time": timestamp, "message": message[:1200]})
        if not events:
            notes.append(
                "No readable kernel events in this window; absence does not exclude an earlier fault."
            )
        return events, list(dict.fromkeys(notes))
