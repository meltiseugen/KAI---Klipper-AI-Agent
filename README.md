# KlipperAI

KlipperAI is a Moonraker-integrated assistant for Klipper and Kalico printers. The project is built around a standalone host daemon, a thin Mainsail integration, and a same-origin web UI that can be opened directly from Mainsail without forking or patching Mainsail for `v1`.

The goal is not to create another printer control plane. The goal is to make troubleshooting, configuration work, and guided printer improvements faster and safer by combining deterministic diagnostics with LLM-assisted reasoning.

## What KlipperAI Aims To Fix

Klipper installations are powerful, but the failure modes are often scattered across different places:

- `klippy.log` shows firmware, config, and MCU failures
- `moonraker.log` shows API and service-side problems
- `systemd` or `journalctl` show host-level issues
- the active config tree may contain subtle include and pin mistakes
- UI users often know what they want to achieve, but not the exact Klipper config they need

KlipperAI is meant to close that gap by giving the user one assistant that can:

- inspect logs and explain what failed
- connect symptoms to likely root causes
- suggest the next safest fix to try
- help generate or improve Klipper config fragments
- review proposed config changes with evidence and comparisons, then edit files manually

## Project Direction

The chosen product shape is:

- standalone Linux daemon on the printer host
- Moonraker underneath as the printer-facing boundary
- supported Mainsail custom-navigation link or button in `v1`
- full-page KlipperAI UI served on the same origin at `/klipperai/`

That gives the project:

- operational separation from Moonraker internals
- easy access to printer state and file metadata through Moonraker
- a low-coupling integration that survives normal Mainsail web updates
- a frontend that can evolve without constantly patching Mainsail for every UI change

## Current State

This repository is an early implementation. What exists today:

- FastAPI-based async agent service
- full-page and embedded chat UI served by the agent
- Moonraker client abstraction
- reconnecting Moonraker agent registration, live printer-state badges and G-code metadata inspection
- bounded tool-using agent loop for OpenAI, with deterministic evidence tools
- read-only config, profile, printer-status and diagnostics tools
- Chat/Debug starting context, a mode selector and saved **Context included** receipts
- literal config search, targeted diagnostic reads and fixed component-status groups
- shutdown investigations for USB/CAN communication and timing failures, with pre-stop statistics and optional kernel-event correlation
- configurable public web search with cited sources
- streamed tool activity and typed completion status
- persistent investigations and dated evidence memory across chats
- printer knowledge built dynamically from each user's hardware details, with public documentation research, cached manuals, reviewed fan-port mappings and Eddy calibration evidence
- static proposal review, section comparisons and read-only revalidation
- direct OpenAI-compatible provider integration path
- private server-side credential setup/rotation, per-task model profiles and persistent provider usage limits
- deterministic [runtime diagnostic rules](docs/runtime-diagnostics.md) for MCU, heater, homing/probe, TMC driver, motion-limit, config-loading and service failures
- host-side current `*.log` collection with configurable line-tail excerpts
- private runtime file logging to `<data_dir>/logs/klipperai.log`
- optional `systemctl` and `journalctl` diagnostics for Moonraker/Klipper and explicitly selected broader service journals
- default-off bounded [host flight recorder](docs/host-diagnostics.md) for incident CPU/process, memory/swap and pressure history
- [typed diagnostic context and API evidence blocks](docs/evidence-contract.md), with source IDs, collection dates, impact ranking and separate confidence hints
- one-time printer-profile detection during install, persisted into `klipperai.cfg`
- firmware flavor detection for mainline Klipper, Kalico, and custom forks
- addon and hardware hint detection for common probes, CAN toolhead boards, and companion services
- persisted capability and geometry detection for probe type, accelerometer, filament sensor, build volume, extruder count, bed mesh, and input shaper state
- config assistant workflow with current-config inspection and first-pass managed include proposals across common config categories
- `systemd` and `nginx` deployment examples
- guided installer support for a Mainsail custom-navigation link
- an optional maintained Mainsail source patch bundle for advanced installs

See [Chat and Debug modes](docs/agent-modes.md) for context contents, limits and
the behavior of the single-pass compatibility workflow.
See [provider management](docs/providers.md) for setup, rotation, model routing,
request/token limits and activation through a manual KlipperAI restart.
See [Moonraker integration](docs/moonraker-integration.md) for socket setup, live
state, non-secret database metadata and the session-bootstrap extension methods.
See [shutdown investigations](docs/shutdown-investigations.md) for supported failure
families, confidence-qualified checks, retained-log limits and missing evidence.
See [investigations and memory](docs/investigations.md) for explicitly confirmed
facts/preferences, incident resolutions and automatic recovery after service restarts.
See [printer knowledge](docs/printer-knowledge.md) to confirm hardware details,
build its local documentation library and understand the initial supported boards.

What does not exist yet:

- continuous host process/CPU, swap and I/O-pressure history for intermittent failures
- complete firmware/hardware validation of proposed configuration
- deeper config specialization beyond the current broad scaffold generation path
- multi-provider support beyond the current OpenAI path

## Feature Vision

### Diagnostics

- analyze `klippy.log`, `moonraker.log`, and host/system log excerpts
- auto-collect current `.log` files from `printer_data/logs`
- send only the configured last lines from each collected log file
- use a separate bounded current/rotated Klippy log search for shutdown investigations
- collect `systemctl show` snapshots and recent `journalctl` lines for `moonraker.service` and `klipper.service`
- write private KlipperAI runtime logs under `<data_dir>/logs/`
- include the active Klipper config tree as LLM context during diagnostics, not only during config-generation requests
- detect common faults deterministically before involving an LLM
- explain likely causes in plain language
- suggest next actions ordered by safety and usefulness

### Config Assistance

- inspect the current printer config tree including the active root config and its include tree
- auto-detect the active root config and follow its include tree recursively
- generate first-pass managed include proposals in chat
- support broad request classes including fan, macro, sensor, probe, heater, input shaper, bed mesh, filament, CAN toolhead, stepper, extruder, and generic scaffolds
- help users create config snippets for macros, sensors, probes, input shaper, CAN, and similar features
- explain why a given config option is needed
- compare current config with the proposed target state
- generate review-only config proposals instead of modifying printer files

### Printer Awareness

- detect firmware flavor from Moonraker update metadata and Klipper repo origin
- summarize host model, distribution, and static printer identity hints
- infer probe type, accelerometer, filament sensor, camera stack, mainboard MCU hints, toolhead board hints, and common addons once during install
- persist detected identity into `[printer_identity]` in `klipperai.cfg`
- persist detected capabilities into `[printer_capabilities]`
- load the saved printer profile at runtime instead of re-detecting on every request

### Embedded UI

- open from Mainsail through a supported custom-navigation entry
- serve a stable standalone page at `/klipperai/`
- keep the embedded iframe route available at `/klipperai/embed`
- keep all provider API keys server-side only

### Workflow Engine

OpenAI requests use a bounded tool loop by default. The model can inspect evidence, call another tool, search public documentation, and then compose a cited answer. Set `web_search_enabled: false` to disable search, or `agent_enabled: false` to use the former single-pass workflow. Search and model calls use provider credits.

- use deterministic diagnostic and configuration tools to supply evidence to the LLM
- keep host access deterministic and tightly bounded
- avoid Rust-backed runtime dependencies in the default host install so embedded printer images can install the package

## Architecture

- `klipperai-agent`: standalone Python daemon on the printer host
- `Moonraker`: canonical source for printer state, managed files, and future integration points
- `Mainsail integration`: supported custom-nav link in `v1`, optional native patch for advanced installs
- `KlipperAI UI`: chat-style assistant UI served from the same origin
- `KlipperAI agent`: LLM-led investigation with read-only evidence tools and manual proposal review

Start discovery at [docs/PROJECT_MAP.md](docs/PROJECT_MAP.md). Runtime and sequence diagrams live in [docs/architecture.md](docs/architecture.md); tool extension and settings are in [docs/agent-development.md](docs/agent-development.md). Memory and manual proposal review are documented in [docs/investigations.md](docs/investigations.md). See [docs/refactoring.md](docs/refactoring.md) for the layout migration and reinstall instructions. Mainsail integration is covered in [docs/mainsail-shell.md](docs/mainsail-shell.md).

## Supported Providers

Current code support:

- `openai`: iterative Responses API tool calling and hosted web search; optional single-pass compatibility mode

Planned provider support is tracked in [BACKLOG.md](BACKLOG.md).

## Installation

### Recommended Path On A Klipper Host

Put the repository on the Linux host that already runs Moonraker and Mainsail or Fluidd. The installer detects standard Linux versus rooted Creality/KE hosts and installs missing application prerequisites automatically. Standard hosts use systemd 250+ with encrypted credentials and an unprivileged account. Native Creality hosts use their init scripts with host-key encryption and RAM-only credential delivery; see [native setup and updates](docs/creality-compatibility.md).

Then run:

```sh
sh install.sh
```

This works from BusyBox `sh`: missing Bash is installed before the Bash phases
start. Setup detects Entware outside PATH and installs Python 3.10+, its required
modules, pip/virtualenv, Git HTTPS support, certificates, utilities and nginx when
missing. Existing vendor nginx is preserved. Fresh supported Creality images
without a package manager get a checksum-pinned Entware bootstrap; existing
`/opt` contents are preserved. Root access, network access and a writable checkout
are required on native hosts. See [prerequisite details](docs/installer-prerequisites.md).

The installer detects `/usr/data/printer_data` and numbered vendor data roots.
Runtime dependencies retain Pydantic v1 and avoid Rust builds. Native MIPS hosts
receive C build tools when needed for the encryption dependency.

To remove a host install later:

```bash
chmod +x uninstall.sh
./uninstall.sh
```

The installer can now patch the Mainsail nginx server block automatically. By default it offers to update one of these common file paths:

- `/etc/nginx/conf.d/mainsail.conf`
- `/etc/nginx/sites-enabled/mainsail`
- `/etc/nginx/sites-available/mainsail`

The installer currently guides the user through:

- choosing the Linux service user
- confirming the project checkout path, default `/home/<service-user>/KlipperAI`
- selecting the LLM provider
- entering the provider API key when needed
- selecting the model name
- pointing KlipperAI at Moonraker, default `http://127.0.0.1:7125`
- confirming the printer data root, default `/home/<service-user>/printer_data`
- confirming the Mainsail config directory, default `/home/<service-user>/printer_data/config`
- creating a Python virtual environment
- installing the package
- writing `/etc/klipperai/klipperai.env` for non-secret bootstrap/install metadata
- provisioning an encrypted master credential and AES-256-GCM provider-key storage using the selected host backend; see [credential storage and recovery](docs/credential-storage.md)
- writing `printer_data/config/klipperai/klipperai.cfg`
- detecting printer profile data once and persisting it into `[printer_identity]` and `[printer_capabilities]`
- writing `printer_data/config/klipperai/klipperai-moonraker.cfg`
- appending an include like `[include klipperai/klipperai-moonraker.cfg]` to `moonraker.conf`
- adding `klipperai-agent` to `printer_data/moonraker.asvc`
- generating and enabling the appropriate systemd or native init service
- generating an nginx location snippet for `/klipperai/`
- optionally patching the selected Mainsail nginx server block to include that snippet
- writing private KlipperAI runtime logs to `<data_dir>/logs/klipperai.log`
- optionally installing a Mainsail navigation link in `.theme/navi.json`
- when OctoEverywhere is detected, optionally applying the local OE `/klipperai/` route patch automatically

KlipperAI requires Python `3.10+`. On older apt-based hosts, setup invokes the
[Python helper](docs/python310-install.md) automatically with one build job, beside
the distro Python. It can recreate an older `.venv` and install a local virtualenv
helper when the embedded Python lacks `venv` support.

The installer always asks for the service user first. Path defaults are then derived from that user, so a `biqu` host will naturally default to `/home/biqu/...` instead of `/home/pi/...`.

After installation, the recommended `v1` flow is:

1. reverse-proxy KlipperAI on the same origin at `/klipperai/`
2. let the installer add a supported Mainsail custom-nav entry
3. open KlipperAI from that Mainsail link

Important limitations:

- the optional native Mainsail shell exists as a source patch bundle, but the installer does not apply or build Mainsail automatically
- the installer does not install Klipper macros, shell-command extensions, or edit `printer.cfg`
- Moonraker update-manager controls work best after the repo has semantic-version tags such as `v0.1.0`

The older `integrations/klipper/install-update-macro.sh` helper remains for
legacy installations; it is outside the supported installation flow. Use the
Moonraker update-manager integration to update the assistant.

`sh install.sh --check` validates the installer modules without changing the
host. The entry point delegates to focused scripts in `deployment/installer/`.
See [frontend and installation ownership](docs/frontend-and-installation.md)
for the module map, access routes, and verification commands.

### Recommended Mainsail Integration

The supported low-coupling integration is a custom navigation entry in Mainsail's `.theme/navi.json` that points to `/klipperai/` and opens KlipperAI in a new browser tab by default.

The repository includes:

- `integrations/mainsail/install-custom-nav.sh`
- `integrations/mainsail/navi.json.example`

The installer also offers automatic sidebar-link repair at startup, on theme
changes and every five minutes. Existing installations can add it with
`sh integrations/mainsail/install-auto-reapply.sh --config-dir /path/to/printer_data/config`.
See the [Mainsail maintenance guide](integrations/mainsail/README.md) for custom
URLs, checks and removal. The OctoEverywhere auto-reapply hook likewise checks at
startup; rerun its hook installer after upgrading to refresh existing units.

Example navigation entry:

```json
[
  {
    "title": "KlipperAI",
    "href": "/klipperai/",
    "target": "_blank",
    "position": 85
  }
]
```

This is the recommended `v1` path because it uses Mainsail's documented custom-navigation support instead of patching or forking Mainsail just to surface the assistant UI.

The former optional topbar/drawer source patch has been retired; the left-menu
link continues to open KlipperAI in a new tab. No custom Mainsail build is needed.
See [Mainsail routing and page verification](docs/mainsail-shell.md) for nginx
configuration, existing-installation follow-up and manual checks.

### Optional OctoEverywhere Host Patch

If you want the main OctoEverywhere printer portal to open KlipperAI at
`/klipperai/` without using a Shared Connection URL, the repository now includes
an unsupported host-side patch bundle in
[integrations/octoeverywhere/README.md](integrations/octoeverywhere/README.md).

This patch modifies the local OctoEverywhere checkout, not Mainsail itself. It
adds a `/klipperai/... -> 127.0.0.1:8811/...` route inside OctoEverywhere's
Moonraker-side router and overrides the `KlipperAI` sidebar click behavior when
loaded via `*.octoeverywhere.com`, with support for opening KlipperAI in a new
tab. If the installer detects an OctoEverywhere checkout, it can offer to apply
this patch automatically. On rooted Creality Nebula Pad-style layouts, the
OctoEverywhere checkout is commonly `/usr/data/octoeverywhere`.

Use it only if you are comfortable carrying a local OctoEverywhere patch. The
optional systemd path/timer hook coordinates Moonraker-managed OE updates: it
removes only KlipperAI's marked blocks when an update is pending, then reapplies
them after the update. Unrelated edits in those OE files are preserved.

### Manual Development Install

#### Windows PowerShell

```powershell
py -3.10 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]
Copy-Item .env.example .env
python -m klipperai_agent
```

#### Linux

```bash
python3.10 -m venv .venv  # or any newer python3.x
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
python -m klipperai_agent
```

Then open the standalone UI in a browser:

- local dev: `http://127.0.0.1:8811/`
- reverse-proxied install: `/klipperai/`

## Runtime Configuration

KlipperAI now uses two configuration surfaces:

- `printer_data/config/klipperai/klipperai.cfg` for host-editable runtime settings
- `/etc/klipperai/klipperai.env` for non-secret bootstrap/install metadata; provider keys use [encrypted private storage](docs/credential-storage.md)

The installer also creates Moonraker integration files:

- `printer_data/config/klipperai/klipperai-moonraker.cfg` for the `update_manager` entry
- `printer_data/moonraker.asvc` to allow Moonraker to restart `klipperai-agent` from frontends such as Mainsail
- an include like `[include klipperai/klipperai-moonraker.cfg]` in `moonraker.conf`

`klipperai.cfg` is loaded at service start. After editing it from Mainsail, restart the agent with:

```bash
sudo systemctl restart klipperai-agent
```

The main `klipperai.cfg` values are:

- `firmware_flavor`: installer-detected firmware flavor
- `firmware_version`: installer-detected firmware version
- `host_model`: installer-detected host computer / SBC model, for example `BigTreeTech CB1`
- `host_distribution`: installer-detected host distribution
- `mainboard`: optional user-declared printer controller board model, for example `BTT Manta E3EZ`
- `toolhead`: optional user-declared toolhead board / electronics name, for example `BTT EBB36`, `FYSETC H36 Combo`, or `Orbiter Nitehawk`
- `probe_type`: installer-detected probe family, including explicit `none` when no probe is found
- `accelerometer`: installer-detected accelerometer family, including explicit `none`
- `filament_sensor`: installer-detected filament sensor family, including explicit `none`
- `bed_mesh_configured`: whether bed mesh is already configured
- `input_shaper_configured`: whether input shaper is already configured
- `canbus_enabled`: installer-detected CAN presence flag
- `addons`: installer-detected addon list
- `root_config_file`: under `[config_context]`, the detected active root config file, overrideable when your root file is not the standard `printer.cfg`
- `ignore_globs`: under `[config_context]`, optional ignore patterns for KlipperAI context collection, such as backups or archived config directories
- `printer_data_root`: printer data directory, usually `/home/<service-user>/printer_data` or `/usr/data/printer_data` on rooted Creality/Nebula-style images
- `mainsail_config_dir`: Mainsail-editable config directory, usually `/home/<service-user>/printer_data/config` or `/usr/data/printer_data/config`
- `root_path`: public reverse-proxy path, usually `/klipperai`
- `port`: local KlipperAI bind port, default `8811`
- `data_dir`: local KlipperAI data directory
- `llm_provider`: `openai`; Chat and Debug require an active API key
- `openai_model`: default OpenAI model name, editable in `klipperai.cfg`
- `logs_dir_path`: host log directory path, usually `/home/<service-user>/printer_data/logs` or `/usr/data/printer_data/logs`
- `agent_log_file_name`, `agent_log_level`: control the KlipperAI runtime log file name and level
- `log_tail_lines_default`: default number of lines to include from each current host log file
- `[log_tail_lines]`: per-log overrides keyed by log stem, for example `klippy = 100` and `moonraker = 200`
- `excluded_logs`: optional denylist for current host log files by name, stem, or glob
- `collect_systemd_diagnostics`: enable or disable service-status and journal collection
- `journal_lines`: number of journal lines to include per service when diagnostics are collected
- `additional_journal_units`: up to six opt-in literal service names, such as `crowsnest.service, nginx.service`
- `host_flight_recorder_enabled`: opt-in Linux host history (default `false`); interval and sample retention are configurable under `[flight_recorder]`
- `enable_write_actions`: obsolete compatibility setting, always forced to `false`
- `memory_cross_chat`: reuse relevant historical observations between chats (default `true`)
- `memory_retention_days`: storage retention (default `90`); storage is `data_dir/investigations.sqlite3`

Environment-file values are intentionally hidden from the Mainsail-editable config:

- `KLIPPERAI_CONFIG_FILE`: points the service at `klipperai.cfg`
- `KLIPPERAI_SERVICE_USER`: hidden install metadata for the service account
- `KLIPPERAI_PROJECT_CHECKOUT_PATH`: hidden install metadata for the checkout path
- `KLIPPERAI_NGINX_SERVER_BLOCK_PATH`: hidden install metadata for the patched nginx server block
- `KLIPPERAI_HOST`: hidden local bind host, default `127.0.0.1`
- `KLIPPERAI_MOONRAKER_URL`: hidden Moonraker base URL, usually `http://127.0.0.1:7125`
- `KLIPPERAI_MANAGED_CONFIG_DIR_NAME`: hidden internal managed-config directory name
- `KLIPPERAI_SESSION_TTL_SECONDS`: hidden UI session lifetime
- `KLIPPERAI_MOONRAKER_SERVICE_NAME`, `KLIPPERAI_KLIPPER_SERVICE_NAME`: hidden systemd unit names for diagnostics
- `KLIPPERAI_SYSTEM_STATUS_ARTIFACT_CHAR_LIMIT`, `KLIPPERAI_JOURNAL_ARTIFACT_CHAR_LIMIT`: hidden clip limits for captured diagnostics
- `KLIPPERAI_SYSTEM_COMMAND_TIMEOUT_SECONDS`: hidden timeout for local diagnostics commands
- `KLIPPERAI_OPENAI_API_KEY`: server-side API key for OpenAI

See [deployment/config/klipperai.cfg.example](deployment/config/klipperai.cfg.example) and [.env.example](.env.example) for the current examples.
For Moonraker integration, see [deployment/moonraker/klipperai-moonraker.cfg.example](deployment/moonraker/klipperai-moonraker.cfg.example).

The installer auto-populates `[printer_identity]` and `[printer_capabilities]` once. If KlipperAI misidentifies the printer hardware, capabilities, or firmware flavor, edit those sections in `klipperai.cfg` and restart the service.

If you are upgrading from an older install that still has a `[printer_geometry]` section in `klipperai.cfg`, remove that section before restarting `klipperai-agent`.

Config collection defaults to the active root config file and its include tree. If your config root is nonstandard or you want KlipperAI to skip backup/archive folders, set those under `[config_context]`.

If you want to repopulate the saved printer profile sections from the current host state later, run:

```bash
source /home/<service-user>/KlipperAI/.venv/bin/activate
klipperai-detect-profile \
  --config-file /home/<service-user>/printer_data/config/klipperai/klipperai.cfg \
  --moonraker-url http://127.0.0.1:7125 \
  --printer-data-root /home/<service-user>/printer_data \
  --overwrite
```

## Security Model

See [Security and local deployment](docs/security.md) for secret storage, redaction,
proxy configuration and upgrade notes. UI sessions are not authentication; the
API assumes a trusted LAN or an authenticated remote proxy.

The security stance is:

- provider API keys stay server-side only
- the browser never gets raw provider credentials
- host access should come from deterministic tools, not arbitrary shell execution by the LLM
- the runtime cannot change printer configuration; users make all printer edits manually
- application-owned memory and runtime logs can be written; storage must stay outside printer config/G-code directories
- `v1` should remain diagnostics-first and read-heavy

## Repository Layout

- `klipperai_agent/`: flat Python package, split by responsibility
- `docs/PROJECT_MAP.md`: task-to-code navigation and generated symbol/test indexes
- `tools/project_map.py`: regenerate architecture discovery artifacts
- `tests/`: unit tests for deterministic logic
- `docs/architecture.md`: system design and responsibilities
- `docs/mainsail-shell.md`: Mainsail integration plan
- `deployment/systemd/`: service examples
- `deployment/nginx/`: reverse-proxy snippet example
- `deployment/moonraker/`: Moonraker integration example
- `integrations/mainsail/`: supported custom-nav helper plus optional patch bundle
- `install.sh`: guided Linux host installer
- `uninstall.sh`: guided Linux host uninstaller
- `BACKLOG.md`: planned work and milestone backlog

## Development Notes

For fixes during real-printer testing, use [the SSH deployment workflow](docs/printer-testing.md):
build the current workspace, deploy it to the printer and roll back the code with
one command. Settings, credentials and history stay on the printer. Release checks
and packaging conventions are in [the release guide](docs/RELEASING.md).

- The FastAPI app exposes `/`, `/healthz`, `/api/ui-sessions`, `/api/bootstrap`, `/api/chat`, `/api/chat/stream`, and `/embed`.
- OpenAI is the provider. Without an API key, the web page offers setup, connection status and saved information; Chat and Debug remain unavailable.
- Requests use an iterative LLM agent that selects tools and follows up on their results. Deterministic checks and templates supply evidence to the model. Conversations, dated evidence and explicitly confirmed memory persist in application-owned SQLite storage. Interrupted investigations resume only when an LLM provider is ready; provider reasoning and HTTP calls are not replayed.
- Host log collection currently targets current `.log` files directly under `printer_data/logs` and sends the configured last lines from each file.
- KlipperAI writes a private rotating runtime log at `<data_dir>/logs/klipperai.log` (normally `/var/lib/klipperai/logs/klipperai.log`). This file is no longer automatically exposed through Mainsail.
- Systemd diagnostics collect `systemctl show` and bounded journals for Moonraker/Klipper, plus journals for explicitly selected additional services. Diagnostics also include fresh core Moonraker state and loaded-config metadata. See [host diagnostics](docs/host-diagnostics.md) for bounds and real-incident replay versus live validation.
- Config assistant currently inspects `printer_data/config`, follows the active root config include tree, and can return typed config proposals in chat across the main supported feature categories.
- The runtime does not apply or write those proposals back to printer files.
- Printer-profile detection currently runs once during install and uses Moonraker `printer`, `machine`, and `update_manager` APIs together with config parsing and Klipper repo-origin hints.
- Diagnostics prompts now include the current Klipper config snapshot in addition to logs, system context, and the saved printer profile.
- Runtime profile awareness now comes from the saved `[printer_identity]` and `[printer_capabilities]` sections in `klipperai.cfg`.
- Host-editable runtime config now lives in `printer_data/config/klipperai/klipperai.cfg`, which is intended to be editable from Mainsail.
- The current UI can be opened directly at `/klipperai/` or embedded via `/klipperai/embed`.

## Status And Roadmap

This is still an early-stage project scaffold, not a finished addon. The current best use of the codebase is to establish the architecture and installation flow before adding deeper printer-aware features.

For planned milestones and open work, see [BACKLOG.md](BACKLOG.md).
