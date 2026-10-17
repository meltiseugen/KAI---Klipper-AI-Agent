"""Parse bounded Klipper excerpts. Counters and clocks never cross a printer restart."""

from __future__ import annotations

import math
import re
from collections import deque

from klipperai_agent.domain.evidence import SourceCitation
from klipperai_agent.domain.shutdown import LogExcerpt, ShutdownIncident

_NUMBER = r"[0-9]+(?:\.[0-9]+)?"
_START = re.compile(rf"^Start printer at .*\(({_NUMBER}) ({_NUMBER})\)")
_STATS = re.compile(rf"^Stats ({_NUMBER}): (.*)")
_ERRORS = (
    ("homing_timeout", re.compile(r"Communication timeout during homing", re.I)),
    (
        "timing",
        re.compile(r"Timer too close|Rescheduled timer in the past|Stepper too far in past", re.I),
    ),
    (
        "communication",
        re.compile(r"Lost communication with MCU|Timeout with MCU|Communication interrupted", re.I),
    ),
)
_NEARBY = re.compile(
    r"can write|No buffer space available|bus.off|USB disconnect|spontaneous restart", re.I
)


def shutdown_family(text: str) -> str | None:
    return next((name for name, pattern in _ERRORS if pattern.search(text)), None)


def _stats(body: str) -> dict[str, float]:
    result: dict[str, float] = {}
    group = ""
    for token in body.split():
        if token.endswith(":"):
            group = token[:-1]
        elif "=" in token:
            key, value = token.split("=", 1)
            if key not in {"sysload", "cputime", "memavail", "bytes_retransmit", "bytes_invalid"}:
                continue
            try:
                number = float(value)
            except ValueError:
                continue
            if math.isfinite(number) and number >= 0:
                name = key if key in {"sysload", "cputime", "memavail"} else f"{group}.{key}"
                result[name] = number
    return result


def summarize_statistics(samples: list[tuple[float, dict[str, float], int]]) -> dict:
    result: dict = {
        "samples": len(samples),
        "scope": "preceding log samples only; not whole-host CPU usage",
    }
    if not samples:
        return result
    result["window_seconds"] = round(samples[-1][0] - samples[0][0], 3)
    for key, label, reducer in [
        ("sysload", "max_load_average_1m", max),
        ("memavail", "min_available_memory_kib", min),
    ]:
        values = [sample[1][key] for sample in samples if key in sample[1]]
        if values:
            result[label] = reducer(values)
    deltas: dict[str, float] = {}
    resets: set[str] = set()
    cpu_rates: list[float] = []
    for before, after in zip(samples, samples[1:]):
        elapsed = after[0] - before[0]
        for key in before[1].keys() & after[1].keys():
            delta = after[1][key] - before[1][key]
            if key == "cputime" or key.endswith((".bytes_invalid", ".bytes_retransmit")):
                if delta < 0:
                    resets.add(key)
                elif key == "cputime":
                    if elapsed > 0:
                        cpu_rates.append(100 * delta / elapsed)
                else:
                    deltas[key] = deltas.get(key, 0) + delta
    result["counter_increases"] = {k: v for k, v in sorted(deltas.items()) if k not in resets}
    result["reset_counters_ignored"] = sorted(resets)
    if cpu_rates and "cputime" not in resets:
        result["max_klippy_cpu_percent_one_core"] = round(max(cpu_rates), 2)
    return result


def parse_shutdowns(excerpt: LogExcerpt) -> list[ShutdownIncident]:
    incidents: list[ShutdownIncident] = []
    samples: deque[tuple[float, dict[str, float], int]] = deque(maxlen=120)
    nearby: deque[tuple[float | None, int, str]] = deque(maxlen=8)
    anchor: tuple[float, float] | None = None
    stopped = False
    lines = excerpt.content.splitlines()
    for index, line in enumerate(lines):
        start = _START.match(line)
        if line.startswith(("Start printer at ", "Restarting printer", "Starting Klippy")):
            samples.clear()
            nearby.clear()
            stopped = False
            anchor = (float(start[1]), float(start[2])) if start else None
            continue
        if stopped:
            continue  # Shutdown dumps repeat old Stats and secondary errors.
        stats = _STATS.match(line)
        if stats:
            sample_time = float(stats[1])
            if not math.isfinite(sample_time):
                continue
            if samples and sample_time <= samples[-1][0]:
                samples.clear()
                nearby.clear()
                anchor = None
            samples.append((sample_time, _stats(stats[2]), index))
            while samples and sample_time - samples[0][0] > 60:
                samples.popleft()
            continue
        if _NEARBY.search(line):
            nearby.append(
                (
                    samples[-1][0] if samples else None,
                    index,
                    f"excerpt line {index + 1}: {line[:350]}",
                )
            )
        family = shutdown_family(line)
        if family is None:
            if re.match(r"^(?:MCU ['\"].* shutdown:|Transition to shutdown state:)", line):
                stopped = True  # Another primary failure preceded any communication fallout.
            continue
        # Match emitted errors, not configuration comments or recovery advice.
        if not re.match(
            r"^(?:MCU |mcu |Lost communication|Timeout with MCU|Transition to shutdown|Communication |!! |Timer too close|Rescheduled timer|Stepper too far|Failed to home|[A-Za-z_]+Error:)",
            line,
        ):
            continue
        event = re.search(rf"eventtime=({_NUMBER})", line)
        stamp: float | None = float(event[1]) if event else (samples[-1][0] if samples else None)
        if stamp is not None and not math.isfinite(stamp):
            stamp = None
        selected = [s for s in samples if stamp is not None and 0 <= stamp - s[0] <= 60]
        unix = anchor[0] + stamp - anchor[1] if anchor and stamp is not None else None
        # Invalid clocks cannot become a journal query. Wall time is an estimate.
        if unix is not None and not 946684800 <= unix <= 4102444800:
            unix = None
        mcu = re.search(r"MCU ['\"]([^'\"]+)['\"]", line, re.I)
        evidence_lines = sorted({s[2] for s in selected[:1] + selected[-1:]} | {index})
        citations = [
            SourceCitation(
                label=f"{excerpt.source} (excerpt line {i + 1})",
                path=f"shutdown:{excerpt.source}",
                excerpt=lines[i][:1000],
            )
            for i in evidence_lines
        ]
        incidents.append(
            ShutdownIncident(
                family=family,
                message=line[:500],
                mcu=mcu[1] if mcu else None,
                source=excerpt.source,
                excerpt_line=index + 1,
                monotonic_time=stamp,
                estimated_unix_time=unix,
                statistics=summarize_statistics(selected),
                nearby_errors=[
                    text
                    for at, pos, text in nearby
                    if index - pos < 200 and (at is None or stamp is None or 0 <= stamp - at <= 60)
                ],
                citations=citations,
            )
        )
        stopped = True
    return incidents
