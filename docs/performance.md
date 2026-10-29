# Performance on constrained printer hosts

KlipperAI shares the host with Klipper and Moonraker. Its local work must remain
bounded while the external LLM performs the investigation. The agent, automatic
config/log collection, read-only tools and manual proposal review remain enabled.
No local model, embedding server, vector database or new runtime dependency was
added by this performance pass. Python 3.10 and Pydantic v1 remain supported.

## Measured improvements

These are synthetic local workloads on Windows 10, CPython 3.13.12, measured before
and after the changes on the same development machine. They are **not ARM printer
benchmarks**. Times are medians of three runs with `tracemalloc` enabled; memory is
the peak traced Python allocation during the operation, excluding the already
loaded application and prebuilt fixture corpus. It is not total process RSS.
Raw results are in [performance-measurements.json](performance-measurements.json).

| Workload | Before | After | Python allocation peak, before → after |
| --- | ---: | ---: | ---: |
| Tail a 16 MiB log containing a very long line | 11,422.8 ms | 0.6 ms | 48.00 → 0.50 MiB |
| Find the active config among 500 inactive backups | 117.7 ms | 4.3 ms | 0.47 → 0.08 MiB |
| List 30 investigations, each with three saved answers | 466.8 ms | 9.4 ms | 4.21 → 0.05 MiB |
| Search twelve dense manuals, returning three passages | 190.2 ms | 190.8 ms | 8.31 → 1.52 MiB |

The manual-search change reduces retained candidates; its measured running time
is essentially unchanged. These numbers should not be used as absolute speed
targets on another machine.

An isolated real application lifespan measured approximately **57.7 MiB working
set**, with **0.015625 CPU seconds over 20 seconds** (about 0.08% of one core).
This Windows sample included the recovery worker but disabled printer connectivity,
provider access and the opt-in flight recorder. It excludes normal investigation
work, document indexing, Linux processes and connected Moonraker traffic.

Repeat the deterministic workloads from the checkout:

```sh
python -m tools.benchmark_resources --repeats 3 --output resource-results.json
```

The tool creates temporary synthetic files/SQLite records and removes them after
the run. It never contacts a printer or model provider. Regression tests enforce
read bounds, data preservation and operation counts instead of fragile timing
thresholds on shared CI hosts.

## Changes and effective bounds

| Area | Behavior |
| --- | --- |
| Interactive investigations | One complete investigation per application process. A second tab receives a retryable conflict before starting another run. Cancellation releases capacity. Recovery waits for the same capacity while keeping its lease alive. |
| Current host logs | Read at most the last 256 KiB per file and return at most the requested line count. Drop a partial first line. Collect at most 16 current logs, prioritizing Klippy, Moonraker and KlipperAI. Gaps and omitted files are reported. Existing exclusions and redaction remain effective. |
| Configuration | Read in bounded chunks and reject files over 1,000,000 decoded characters before parsing them. Prefer a conventional `printer.cfg` containing `[printer]`; explicit configured roots take precedence. Nonstandard-root discovery retains its fallback. Active includes still load automatically. |
| Config excerpts | Runtime composition retains the existing 100-document and 24,000-character excerpt limits. Full-document expansion remains hash-checked and capped at 1,000,000 characters. Collection errors are evidence gaps. |
| Sidebar reads | The summary endpoint queries metadata and pending state without loading saved turns. Agent cross-chat recall retains its separate evidence-bearing recent-history read. |
| Browser startup | Load sidebar summaries first. Fetch a full saved conversation when opened, preserving cached history, mode preferences and drafts if fetching fails. Active conversation refreshes still fetch updated outcomes. |
| Browser history refresh | Poll every 5 seconds while an investigation is pending, every 30 seconds otherwise. Pause polling in hidden tabs and refresh on return. Prevent overlapping refreshes. |
| Recovery checkpoints | Heartbeats update lease ownership/deadline state without parsing or serializing the saved evidence JSON. Evidence is checkpointed after completed tool actions. SQLite still controls physical page/journal writes. |
| Manual retrieval | Keep only the best three passage candidates while scanning. Preserve score ordering, source hashes, page locations and citation excerpts. |
| Agent log searches | New read-only tools use at most four sources per search, 256 KiB windows, eight cached windows and 12 MiB reserved read/decompression work per investigation. Compressed logs reserve an 8 MiB allowance each. [Search contracts](log-and-config-search.md) describe cursors and source limits. |
| Expanded config cache | At most 4,000,000 decoded characters across expanded references per investigation; failures remain evidence gaps. |

## Other subsystems reviewed

| Subsystem | Existing cost controls and remaining considerations |
| --- | --- |
| LLM loop | Defaults: eight model steps, twelve tool calls, 180-second run budget, 120,000 context characters and 16,000 characters per tool result. Request-local caches avoid repeated identical tool work. Network/model latency is separate from local CPU cost. |
| Moonraker | One shared Unix-socket connection with fixed event subscriptions and a 30-second refresh heartbeat. Browser streams coalesce revision changes and send lightweight heartbeat comments while unchanged. These connected costs were not part of the isolated idle measurement. |
| Diagnostics | Blocking file/service reads run in worker threads. Rotated shutdown logs are separately bounded: three files, 2 MiB tails, and 16 MiB decompression allowance per compressed log. Compressed rotations can still consume noticeable CPU. |
| Flight recorder | Disabled by default. If enabled, samples no faster than every five seconds; default ten seconds/1,440 samples. Existing byte and sample quotas cap its SQLite database at 16 MiB. Sampling writes to application storage and adds CPU/I/O. |
| Documentation | Research runs only when explicitly requested and processes sources sequentially. Downloads are capped at 8 MiB; text is bounded. PDF parsing is isolated in a child process with a 12-second deadline, page/stream limits and a Linux 384 MiB virtual-address-space ceiling. That ceiling is not a promised RAM footprint. |
| Cached documents | Existing quotas retain two versions per source, at most 72 document versions and 128 MiB of original-document payload per printer. Metadata, SQLite free pages and transaction journals add disk overhead. |
| Investigation storage | Existing 90-day retention, 1,000 completed-turn ceiling and 100 pending-run ceiling remain. These are count/age bounds, **not a global byte quota**. Large retained evidence can still consume substantial disk space; no saved history was automatically removed by this pass. |
| Application logs | Rotation defaults to a 2 MiB current file and five backups, approximately 12 MiB total. Uvicorn access logging is disabled. |
| Installation | One Uvicorn worker. No development dependency was added to the runtime package. Existing installer compilation/cache space and package versions must be measured on the actual target architecture. |

## Hardware acceptance still required

The software improvements do not establish that every 128/256 MiB printer host
has enough spare RAM. Klipper, Moonraker, cameras, OS page cache and vendor services
already consume part of the machine. Available storage and swap differ as well.
The minimum supported host cannot be certified from a Windows development machine.

Before calling a low-memory host supported, measure the installed service on the
weakest intended Linux/ARM target during an actual print:

1. Record total/available RAM, swap, free storage, CPU model and existing service
   load. Measure daemon idle RSS/CPU with Moonraker connected and zero/one/multiple
   visible browser tabs. Proposed acceptance: idle CPU below 1% of one core and
   idle daemon RSS below 96 MiB; verify rather than assume these targets.
2. Run Chat and Debug with representative active includes, long logs and retained
   investigations. Record daemon/child-process peak RSS, CPU time, disk I/O and
   print timing. Confirm no sustained swap, OOM kill, MCU timeout or print degradation.
3. Test a near-limit PDF and compressed rotated logs separately. Record the combined
   daemon/child peak; a parser failure must preserve the downloadable original.
   Avoid certifying 256 MiB hardware from the ordinary chat workload alone.
4. Fill history and documentation caches with representative evidence. Measure
   physical database/journal sizes and free-space behavior. A non-destructive
   global investigation-storage quota and a deliberate reclamation policy remain
   necessary before promising a hard disk ceiling on very small storage devices.
5. Re-run the benchmark and smoke-test the installed wheel outside the checkout.
   Record package disk usage and cold startup time on that architecture. Do not
   equate the synthetic timing table with real provider or printer validation.

These acceptance checks require access to the intended printer host. They are not
reported as completed by the local regression suite.
