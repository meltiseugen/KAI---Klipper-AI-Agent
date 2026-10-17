from __future__ import annotations

import pytest

from klipperai_agent.diagnostics.rules import RuleEngine
from klipperai_agent.diagnostics.shutdown import parse_shutdowns, summarize_statistics
from klipperai_agent.diagnostics.shutdown_assessment import assess_shutdown
from klipperai_agent.domain.evidence import ArtifactInput
from klipperai_agent.domain.shutdown import HostObservation, LogExcerpt

START = "Start printer at Thu Oct 15 10:00:00 2026 (1792058400.0 100.0)"


def stats(t, cpu=1, memory=100000, invalid=4, retransmit=8):
    return (
        f"Stats {t}: gcodein=12 mcu: bytes_write=900 bytes_retransmit=0 bytes_invalid=0 "
        f"toolhead: bytes_retransmit={retransmit} bytes_invalid={invalid} "
        f"sysload=2.5 cputime={cpu} memavail={memory} print_time=50 buffer_time=0"
    )


def incident(*lines):
    return parse_shutdowns(LogExcerpt("klippy.log", "\n".join(lines)))[0]


def test_shutdown_uses_only_preceding_same_run_statistics_and_first_error():
    failure = incident(
        START,
        stats(101),
        "Got error -1 in can write: (105)No buffer space available",
        stats(102, 1.9, 20000, 7, 20),
        "Timeout with MCU 'toolhead' (eventtime=102.5)",
        "Lost communication with MCU 'toolhead'",
        stats(105, 999, 0, 100, 999),
        "MCU 'mcu' shutdown: Timer too close",
    )
    assert failure.family == "communication" and failure.mcu == "toolhead"
    assert failure.estimated_unix_time == 1792058402.5
    assert failure.statistics["samples"] == 2
    assert failure.statistics["max_klippy_cpu_percent_one_core"] == 90
    assert failure.statistics["min_available_memory_kib"] == 20000
    assert failure.statistics["max_load_average_1m"] == 2.5
    assert failure.statistics["counter_increases"] == {
        "mcu.bytes_retransmit": 0,
        "mcu.bytes_invalid": 0,
        "toolhead.bytes_invalid": 3,
        "toolhead.bytes_retransmit": 12,
    }
    causes = assess_shutdown(failure, HostObservation(), {"toolhead": "CAN"})
    text = str([item.model_dump() for item in causes])
    assert "Low available memory" in text and "not proof of OOM" in text
    assert "Klippy CPU pressure" in text and "packet ordering" in text
    assert "not proof of a bad cable" in text and "does not mean host RAM" in text
    assert all(source.line_number is None for source in failure.citations)
    assert "excerpt line" in failure.citations[0].label


def test_restarts_reset_clocks_and_counters_and_ignore_secondary_errors():
    content = "\n".join(
        [
            START,
            stats(101),
            stats(102),
            "MCU 'mcu' shutdown: ADC out of range",
            "Lost communication with MCU 'mcu'",
            "Restarting printer",
            stats(2, 999),
            "Starting Klippy...",
            stats(3, 2, invalid=100),
            stats(4, 1, invalid=0),
            "MCU 'toolhead' shutdown: Timer too close",
            START,
            stats(101),
            "Communication timeout during homing probe",
        ]
    )
    failures = parse_shutdowns(LogExcerpt("klippy.log", content))
    assert [item.family for item in failures] == ["timing", "homing_timeout"]
    assert failures[0].estimated_unix_time is None
    assert "toolhead.bytes_invalid" in failures[0].statistics["reset_counters_ignored"]
    assert "max_klippy_cpu_percent_one_core" not in failures[0].statistics
    assert "toolhead.bytes_invalid" not in failures[0].statistics["counter_increases"]
    assert (
        "Do not raise TRSYNC_TIMEOUT"
        in assess_shutdown(failures[1], HostObservation(), {})[0].next_steps[0]
    )


def test_sample_window_missing_clocks_stale_errors_and_malformed_numbers():
    failure = incident(
        START,
        stats(100),
        "No buffer space available",
        stats(170),
        stats(171)
        .replace("cputime=1", "cputime=broken")
        .replace("memavail=100000", "memavail=nan"),
        "# Timer too close is an example",
        "MCU 'mcu' shutdown: Rescheduled timer in the past",
    )
    assert failure.statistics["samples"] == 2 and not failure.nearby_errors
    reset = incident(START, stats(110), stats(109), "Lost communication with MCU 'mcu'")
    assert reset.estimated_unix_time is None and reset.statistics["samples"] == 1
    absent = incident("Communication interrupted")
    assert absent.monotonic_time is None and absent.statistics["samples"] == 0
    assert (
        assess_shutdown(absent, HostObservation(current={"system_cpu_usage": {"cpu": 100}}), {})[
            0
        ].cause
        == "Cause not established"
    )
    invalid = incident("Start printer at bad (1.0 100.0)", stats(101), "Timer too close")
    assert invalid.estimated_unix_time is None
    huge = "9" * 400
    bad = incident(f"Stats {huge}: cputime=2", f"Timeout with MCU 'mcu' (eventtime={huge})")
    assert bad.monotonic_time is None
    assert (
        summarize_statistics([(1, {"cputime": 1}, 0), (1, {"cputime": 2}, 1)])["window_seconds"]
        == 0
    )


@pytest.mark.parametrize(
    "message,cause",
    [
        ("Out of memory: Killed process 42 (klippy)", "Host memory exhaustion"),
        ("usb 1-1: USB disconnect, device number 3", "USB link interruption"),
        ("can0: bus-off", "CAN bus fault"),
        ("mmc0: I/O error", "Host storage fault"),
        ("Under-voltage detected!", "Host power or thermal throttling"),
    ],
)
def test_kernel_hypotheses_are_supported_not_claimed_root_causes(message, cause):
    failure = incident("Lost communication with MCU 'mcu'")
    hypotheses = assess_shutdown(
        failure, HostObservation(kernel=[{"unix_time": 1792058400, "message": message}]), {}
    )
    assert hypotheses[0].cause == cause and "causation unproven" in hypotheses[0].confidence


def test_nonzero_counters_and_load_average_do_not_prove_a_fault():
    failure = incident(stats(100), stats(101), "Timer too close")
    assert assess_shutdown(failure, HostObservation(), {})[0].cause == "Cause not established"
    invalid = incident(stats(100), stats(101, invalid=5), "Timer too close")
    assert "Confirm this MCU" in assess_shutdown(invalid, HostObservation(), {})[0].next_steps[0]


def test_rules_recognize_shutdown_families_without_prescribing_blind_tuning():
    findings = RuleEngine().analyze(
        [
            ArtifactInput(
                kind="klippy_log",
                content="Lost communication with MCU 'mcu'\nCommunication timeout during homing\nRescheduled timer in the past\nTimer too close",
            )
        ]
    )
    assert {finding.code for finding in findings} == {
        "mcu_timer_too_close",
        "mcu_past_timer",
        "mcu_communication_lost",
        "mcu_homing_timeout",
    }
    assert "Reduce acceleration" not in str(findings)
