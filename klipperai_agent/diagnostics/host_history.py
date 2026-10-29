"""Select historical observations without conflating them with current state."""

from __future__ import annotations

from klipperai_agent.domain.host_history import HostSample


def summarize_history(samples: list[HostSample], stamp: float) -> dict:
    # Only intervals ending before the incident can support a pre-stop hypothesis.
    before = [item for item in samples if item.unix_time <= stamp]
    summary: dict = {}
    for name, values, choose in (
        ("max_cpu_busy_percent", [(s.unix_time, s.cpu_busy_percent) for s in before], max),
        ("max_iowait_percent", [(s.unix_time, s.cpu_iowait_percent) for s in before], max),
        (
            "min_available_memory_kib",
            [(s.unix_time, s.memory_kib.get("MemAvailable")) for s in before],
            min,
        ),
        (
            "max_io_some_avg10",
            [(s.unix_time, s.pressure["io"].some_avg10) for s in before if "io" in s.pressure],
            max,
        ),
        (
            "max_memory_some_avg10",
            [
                (s.unix_time, s.pressure["memory"].some_avg10)
                for s in before
                if "memory" in s.pressure
            ],
            max,
        ),
    ):
        available = [(time, value) for time, value in values if value is not None]
        if available:
            time, value = choose(available, key=lambda pair: pair[1])
            summary[name] = {"unix_time": time, "value": value}
    selected = sorted(
        sorted(samples, key=lambda s: abs(s.unix_time - stamp))[:6], key=lambda s: s.unix_time
    )
    return {
        "scope": "Historical sampled host observations near an estimated incident time; correlation does not prove causation.",
        "window_start": stamp - 90,
        "window_end": stamp + 10,
        "sample_count": len(samples),
        "pre_stop_sample_count": len(before),
        "pre_stop_summary": summary,
        "samples": [sample.model_dump() for sample in selected],
        "truncated": len(samples) > len(selected),
        "notes": [
            "Samples can miss short spikes and unobserved processes. CPU process rates are percent of one core; RSS is KiB. PSI avg10 is percent stalled over ten seconds; VM counters are cumulative, not rates.",
            "Clock adjustments, reboots, downtime and retention can leave gaps. Post-stop samples are context only and are excluded from the pre-stop summary.",
        ]
        + (
            []
            if before
            else ["No retained pre-stop samples; historical host cause remains unconfirmed."]
        ),
    }
