# Host history and core diagnostic state

Diagnostics collect fresh Moonraker server info, printer info and known status
objects. The `Moonraker core state` artifact records collection time, API sources,
printer state, temperatures, print status and loaded-config metadata. Object reads
use a fixed field allowlist and the available-object list. Failed printer reads
retain server/log evidence and explain what is missing.

Loaded-config metadata includes section names/count, `save_config_pending` and
bounded warnings. It excludes option values and reflects the last Klipper
start/restart, which may differ from files currently on disk. No `SAVE_CONFIG`
command is executed. See the [Moonraker query API](https://moonraker.readthedocs.io/en/latest/external_api/printer/#query-printer-object-status)
and [Klipper configfile status](https://www.klipper3d.org/Status_Reference.html#configfile).

## Optional broader service journals

In `klipperai.cfg`, extend `[system]` with an explicit selection:

```ini
[system]
collect_systemd_diagnostics: true
journal_lines: 200
additional_journal_units: crowsnest.service, nginx.service
```

The default list is empty. At most six literal `.service` names are accepted;
paths, wildcards and command arguments are rejected. Duplicate units, including
the configured Moonraker/Klipper units, are collected once. Additional units get
journal reads only. The main system-diagnostics switch gates all service reads;
the model cannot supply unit names or commands. Restart the agent after editing.
For direct development, `KLIPPERAI_ADDITIONAL_JOURNAL_UNITS` accepts the same
comma-separated names.

Journal reads are capped at 1,000 entries, 256 KiB of captured stdout/stderr per
stream, the configured text limit, and the command timeout (default six seconds).
Status reads retain at most 64 KiB per stream. Missing tools, access denials,
empty results and truncated output are explicit collector notes. A successful
read is limited to records accessible to the service account. Subprocess output
is spooled to temporary files while the command runs; temporary disk usage during
that command is not capped. No sudo or service mutation is used.

## Opt-in flight recorder

The recorder is disabled by default. Enable it explicitly on the Linux printer
host in `klipperai.cfg`, then manually restart the KlipperAI agent:

```ini
[flight_recorder]
host_flight_recorder_enabled: true
host_flight_recorder_interval_seconds: 10
host_flight_recorder_max_samples: 1440
```

The application lifespan starts one worker and waits for its bounded in-progress
sample/write on shutdown. Sampling is independent of chat/provider availability;
model tools only read retained observations. Disabling recording stops sampling
after restart and excludes history from investigations. The private database
remains on disk until manually removed with the agent stopped; it is separate
from conversation deletion.

Each sample uses fixed read-only Linux `/proc` paths:

- Aggregate CPU busy and I/O-wait percentages from counter deltas. Busy excludes
  idle and I/O wait; guest time is not counted twice. I/O wait is a kernel estimate,
  not proof of a storage fault.
- `MemTotal`, `MemAvailable`, `SwapTotal`, `SwapFree` in KiB; cumulative `pswpin`,
  `pswpout` (pages), `pgpgin`, `pgpgout` (KiB) and `oom_kill` counters.
- CPU/memory/I/O PSI `some` and `full` ten-second averages (percent stalled) and
  cumulative stall microseconds, when supported by the kernel.
- Up to eight processes selected from CPU and RSS rankings. PID, short process
  name, CPU percent of one core and RSS KiB are retained. Process arguments,
  environment, open files and arbitrary filesystem contents are never read.

At most 256 process reads and 4,096 directory entries are considered per sample.
Proc files retain at most 64 KiB; each process stat retains at most 4 KiB.
The process scan is partial when capped; inaccessible/exited processes are noted.
Process identity includes the start counter internally to avoid PID-reuse rates.
The initial sample, reboot and detected wall-clock discontinuities have no CPU
rate. New processes have no prior interval. Missing PSI support preserves other
measurements. See the [proc reference](https://docs.kernel.org/filesystems/proc.html)
and [pressure-stall reference](https://docs.kernel.org/accounting/psi.html).

The interval is 5–300 seconds. Retention is 12–8,640 samples, with 1,440 samples
at ten seconds providing approximately four hours of continuous recording.
`data_dir/host-history.sqlite3` is private (owner-only permissions on POSIX), rejects
symlinks/hardlinks and printer config/log/G-code destinations, and survives agent
restarts. Individual records are capped at 16 KiB; total JSON payload is capped at
8 MiB with oldest records removed first. The SQLite database is limited to 16 MiB;
a transient rollback journal can add up to roughly another database's size.
Older data can be evicted before the sample-count limit. There is no growing WAL,
unbounded queue, added dependency, shell command or privileged process access.

## Incident interpretation

`investigate_shutdown` reads samples from 90 seconds before to ten seconds after
an estimated incident time. No usable log clock anchor means no guessed history
correlation. It reports sample counts, a pre-stop summary, and at most six nearby
full samples. Further report/context budgets can omit samples explicitly.
Post-stop measurements never enter the pre-stop summary. Historical observations
get a source citation and remain separate from current Moonraker host readings.

CPU busy at least 90%, or memory/I/O PSI `some avg10` at least 20%, adds a qualified
possible-contributor assessment. These are heuristics, not proof of causation,
failed storage, OOM or a USB/CAN defect. Sampling, process limits, clock changes,
downtime and eviction can miss short events. Healthy retained samples do not rule
out a spike. Enable recording before a supervised reproduction; it is not a hard
real-time tracer.

## Real-incident replay and live answer review

Run the sourced public incident corpus without a provider or printer:

```sh
python -m tools.validate_shutdown
```

The default private output is `.local/shutdown-validation.json`. The source
manifest, `tests/fixtures/shutdown/cases.json`, records attachment URLs/digests,
exact original line positions, excerpt hashes, reported transports and expected
observations. Excerpts contain sparse, unmodified machine-generated
startup/Stats/failure lines; their summaries cover only retained samples.

- [USB cold-start incident, Klipper issue 1083](https://github.com/Klipper3d/klipper/issues/1083):
  detects MCU communication loss and leaves the physical cause unconfirmed without
  dated kernel evidence. Nonzero starting counters are not new faults.
- [CAN timing incident, Klipper Discourse 16908](https://klipper.discourse.group/t/timer-too-close-random/16908):
  detects `Timer too close`, increasing invalid bytes and retransmissions, and
  recommends packet-ordering/software investigation. The excerpt has no startup
  anchor, so incident wall time stays unknown. The complete 97.6 MB log exceeds
  runtime bounds; this replay does not imply full runtime coverage of that file.

To collect real model answers, use the deployment's configured provider policy
and private credential:

```sh
python -m tools.validate_shutdown --live-provider
```

This explicitly consumes credits and sends only public replay reports through
the existing provider usage guard. It makes no printer reads or commands.
Reports separate automated replay, live-provider collection and live printer
status. Saved answers contain only public final output. Successful generation
is marked **pending human review** against included criteria; it never
automatically counts as validated diagnostic quality. Live printer reproduction
and Linux permissions/overhead remain separate checks.
