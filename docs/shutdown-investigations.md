# Investigating MCU communication and timing shutdowns

Choose **Debug** and describe the shutdown, for example:

> The printer stopped with a communication/timing error. I use USB and CAN.
> Investigate the latest failure, explain the strongest evidence and missing
> information, and suggest a targeted fix and a way to verify it.

Debug automatically runs `investigate_shutdown` when the question or initial
diagnostics mention communication, timing or shutdown failures. Chat exposes the
same tool for relevant follow-up investigations. This requires the tool-using
agent; the offline stub has the expanded deterministic signature rules only.
There are no printer writes, firmware flashes, service restarts or active CAN
discovery scans. All proposed fixes remain manual.

## Evidence and interpretation

The investigator recognizes lost/interrupted MCU communication, `Timer too close`,
`Rescheduled timer in the past`, `Stepper too far in past`, and communication
timeouts during homing. It retains the first supported failure in each detected
printer run, excludes subsequent shutdown dumps, and avoids treating communication
fallout after another primary shutdown (such as ADC failure) as the original cause.

For each incident it examines up to 60 seconds/120 preceding `Stats` records:

- Minimum available memory in KiB. Below 32 MiB is explicitly a heuristic warning,
  not proof of an OOM kill or a recommendation to clear caches.
- Maximum Klippy process CPU rate, calculated from cumulative `cputime` differences
  divided by elapsed time. An 80% one-core rate is a heuristic, not whole-host CPU
  saturation or identification of a competing process.
- One-minute `sysload`, reported as load average, never CPU percentage.
- Changes in each MCU's `bytes_invalid` and `bytes_retransmit` counters. A nonzero
  starting value alone is not a new error; counters that reset are excluded.
- Nearby CAN transmit queue errors. `No buffer space available` is not evidence
  that the host's RAM is exhausted.

The on-disk active configuration identifies CAN versus serial connections; a
serial connection still needs USB/UART confirmation from the device path. It can
differ from the configuration loaded when the incident occurred. CAN invalid-byte
increases point to a packet-ordering/software investigation; retransmissions alone
do not identify a faulty cable. Homing communication timeouts get their own checks
for endstop/probe and motor MCU assignments and latency. The agent must not suggest
raising safety timeouts to mask the fault.

When a `Start printer at` clock anchor and preceding Stats/timeout timestamp are
available in the same excerpt/run, the collector queries retained kernel journal
events from 90 seconds before to 10 seconds after the estimated incident time.
It checks OOM/process kills, USB disconnections/resets, CAN bus-off, storage errors,
and power/thermal warnings. These are supporting observations, not automatic proof
of causation. The window may contain effects of the shutdown as well as causes.
Clock adjustments can invalidate correlation. Missing anchors disable the query
instead of guessing a wall time from file modification time.

Moonraker `/machine/proc_stats` supplies a separate, explicitly current snapshot of
host CPU, memory, temperature, uptime and throttling flags. A healthy host now
cannot rule out a past spike. Historical throttle bits have no incident timestamp
and are not automatically attributed to the stop.

The report contains confidence descriptions, supporting excerpts, manual next
steps, current-state labels and missing-evidence notes. Public reports and source
citations use the existing investigation persistence and Context included receipts.
The model receives observations; no private reasoning is stored.

## Bounds and incomplete evidence

- Search current `klippy.log` and the two most recently modified eligible rotations
  (or the three most recent rotations when the current file is absent). Eligible
  names have numeric/date suffixes, optionally `.gz`. Symlinks and unrelated names
  are skipped. Each file retains at most its final 2 MiB; compressed reads stop
  after 16 MiB decompressed and reject compressed inputs over 16 MiB, reporting
  that file unavailable. Earlier bytes and
  files are not claimed to have been searched.
- Honor `collect_host_logs`, the configured log directory and exclusions.
  Excluding `klippy`/`klippy.log` also excludes rotations. This dedicated read has
  its own byte bounds; ordinary `log_tail_lines_*` settings still govern the
  general diagnostics tool. Supplied Klippy artifacts can be analyzed when host
  reads are disabled.
- Honor `collect_systemd_diagnostics` for kernel reads. Use a fixed `journalctl`
  command with a timestamp window and at most 200 records; `_TRANSPORT=kernel`
  allows retained earlier boots. No sudo, service mutation or model command/path
  argument is available. Output is spooled to temporary files with the configured
  command timeout, then read with a 256 KiB cap per stream. Temporary disk usage
  during the command is not byte-capped. Incomplete/access-limited records are
  explicitly reported; absent events do not prove absence of a fault.
- Return at most ten incident summaries, newest first when every incident is dated;
  otherwise use current/recent-file and reverse run order, explicitly provisional.
  `incident_index` selects one of these incidents. An affected MCU/known failure
  time supplied by the user helps confirm the selected event is the right one.
- Bound report size, assessments and source excerpts. Labels use **excerpt lines**,
  never pretend they are original file lines. Existing registry/context budgets
  may further truncate the report and mark it partial.

There is no continuous host process/CPU/pressure recorder. Existing logs cannot
identify every short CPU, swap, I/O or power spike. Long prints may push the clock
anchor or failure outside the read window, and rotation/volatile journals may
remove evidence. Preserve the logs promptly and use a supervised reproduction
when evidence is insufficient. A future opt-in bounded flight recorder could
capture the missing process history; this implementation does not claim to do so.

## Implementation and validation

`domain/shutdown.py` holds observations; `diagnostics/shutdown.py` parses runs and
statistics; `shutdown_assessment.py` builds evidence-based hypotheses.
`infrastructure/host/shutdown*.py` owns filesystem, Moonraker and kernel reads;
`agent/ports.py` exposes the narrow reader protocol. The tool and Debug starting
context are composed in `agent/` and wired in `bootstrap/container.py`.

`test_shutdown.py`, `test_shutdown_host.py` and `test_shutdown_agent.py` cover
failure families, clock/counter resets, unrelated primary failures, pre/post-stop
separation, file/byte limits, exclusions, malformed/missing evidence, fixed API and
journal requests, argument rejection, timeouts, report bounds, model handoff and
HTTP persistence. These are offline fixtures/scripted models; real Linux journal
access, printer fault diagnosis and live provider answer quality need live checks.

## Research references

Reviewed 2026-10-15; implementation guidance, not evidence of a specific printer's fault:

- [Klipper debugging and log analysis](https://www.klipper3d.org/Debugging.html)
- [Klipper CAN troubleshooting](https://www.klipper3d.org/CANBUS_Troubleshooting.html)
- [Klipper multi-MCU homing](https://www.klipper3d.org/Multi_MCU_Homing.html)
- [Klipper host statistics implementation](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/statistics.py)
- [Klipper startup clock anchor](https://github.com/Klipper3d/klipper/blob/master/klippy/klippy.py)
- [Moonraker process statistics](https://moonraker.readthedocs.io/en/latest/external_api/machine/#get-process-statistics)
- [journalctl matching and time windows](https://www.freedesktop.org/software/systemd/man/latest/journalctl.html)
