"""Evidence-backed hypotheses, never automatic printer fixes."""

from __future__ import annotations

import re

from klipperai_agent.domain.shutdown import CauseAssessment, HostObservation, ShutdownIncident

SOURCES = {
    "Klipper log analysis": "https://www.klipper3d.org/Debugging.html",
    "CAN troubleshooting": "https://www.klipper3d.org/CANBUS_Troubleshooting.html",
    "Multi-MCU homing": "https://www.klipper3d.org/Multi_MCU_Homing.html",
}


def assess_shutdown(
    incident: ShutdownIncident, host: HostObservation, transports: dict[str, str]
) -> list[CauseAssessment]:
    assessments: list[CauseAssessment] = []

    def add(cause: str, confidence: str, evidence: list[str], *steps: str) -> None:
        assessments.append(
            CauseAssessment(
                cause=cause, confidence=confidence, evidence=evidence, next_steps=list(steps)
            )
        )

    categories = (
        (
            "Host memory exhaustion",
            r"out of memory:|oom-kill|invoked oom-killer|Killed process \d+",
            "Identify the process named by the OOM event and its memory growth; reduce or repair that workload before a supervised test. Check whether Klippy itself was killed.",
        ),
        (
            "USB link interruption",
            r"usb .*disconnect|usb .*reset .*USB device|tty(?:USB|ACM)\d.*disconnect",
            "Match the USB device/port to the affected MCU. With the printer safely powered down, inspect power, cable, connectors and interference; change one suspect component at a time.",
        ),
        (
            "CAN bus fault",
            r"(?:can\d|can bus|canbus).*bus.off|bus.off.*can",
            "Check CAN power, connectors, wiring topology and termination with the printer safely powered down. Compare host/bridge firmware and kernel versions with current Klipper guidance.",
        ),
        (
            "Host storage fault",
            r"I/O error|mmc.*(?:timeout|error)|EXT4-fs error",
            "Preserve logs and back up configuration. Investigate storage media and power before replacing or repairing the affected storage.",
        ),
        (
            "Host power or thermal throttling",
            r"under.voltage|voltage normalised|thermal.*thrott|temperature.*thrott",
            "Check host power supply/cable and cooling. Correlate the warning with the stop; a historical throttle flag alone cannot date the fault.",
        ),
    )
    for cause, pattern, step in categories:
        matches = [event for event in host.kernel if re.search(pattern, event["message"], re.I)]
        if matches:
            add(
                cause,
                "supported by nearby host events; causation unproven",
                [f"{event['unix_time']}: {event['message'][:350]}" for event in matches[:3]],
                step,
            )
    stats = incident.statistics
    memory = stats.get("min_available_memory_kib")
    if memory is not None and memory < 32768:
        add(
            "Low available memory before the stop",
            "possible contributor; not proof of OOM",
            [f"Minimum MemAvailable: {memory:g} KiB (heuristic warning below 32 MiB)."],
            "Look for contemporaneous OOM, swap or I/O pressure evidence and the responsible process. A low value alone does not justify blaming RAM or clearing caches.",
        )
    cpu = stats.get("max_klippy_cpu_percent_one_core")
    if cpu is not None and cpu >= 80:
        add(
            "Klippy CPU pressure before the stop",
            "possible contributor",
            [f"Klippy process CPU delta reached {cpu:g}% of one core over a sampled interval."],
            "Capture host process CPU, I/O wait and pressure during a safe supervised reproduction. Review heavy macros, plugins and competing jobs; this sample does not identify another process or prove host-wide saturation.",
        )
    for key, delta in stats.get("counter_increases", {}).items():
        if delta <= 0:
            continue
        mcu, counter = key.rsplit(".", 1)
        if counter == "bytes_invalid":
            is_can = transports.get(mcu) == "CAN"
            add(
                f"Invalid protocol bytes on {mcu}",
                "supported anomaly; cause requires transport confirmation",
                [f"{key} increased by {delta:g} before the stop."],
                "CAN configuration detected: investigate packet ordering and host/bridge firmware versions using Klipper CAN guidance; do not assume wiring caused invalid bytes."
                if is_can
                else "Confirm this MCU's USB/CAN/UART transport from active configuration. For CAN, investigate packet ordering and software versions; for serial links inspect communication integrity and firmware compatibility.",
            )
        else:
            add(
                f"Retransmissions on {mcu}",
                "supported anomaly; not proof of a bad cable",
                [f"{key} increased by {delta:g} before the stop."],
                "Compare timing, power, kernel link events and other MCUs. Retransmissions alone cannot distinguish host stalls, transport faults or an unresponsive MCU.",
            )
    if any("No buffer space available" in text for text in incident.nearby_errors):
        add(
            "CAN transmit queue pressure",
            "possible contributor or symptom of a bus failure",
            [text for text in incident.nearby_errors if "No buffer space available" in text],
            "Check CAN link health and configured txqueuelen against Klipper documentation. This message does not mean host RAM is full; an excessively large queue can worsen latency.",
        )
    if incident.family == "homing_timeout":
        add(
            "Multi-MCU homing communication latency",
            "failure class identified; root cause unknown",
            [incident.message],
            "Identify which MCU owns the endstop/probe and which owns the motors. Inspect communication latency, CAN/USB errors and host scheduling around homing. Do not raise TRSYNC_TIMEOUT or disable safeguards.",
        )
    if not assessments:
        add(
            "Cause not established",
            "insufficient evidence",
            [incident.message],
            "Preserve klippy.log and rotations before restarting again. Capture host process/CPU, available memory, I/O pressure and kernel events during a safe supervised reproduction.",
            "For USB inspect the affected device's power/cable/port; for CAN verify wiring/termination and host/bridge versions. Choose checks using the affected MCU's configuration, not guesswork.",
        )
    assessments.sort(key=lambda item: 0 if item.confidence.startswith("supported") else 1)
    return assessments
