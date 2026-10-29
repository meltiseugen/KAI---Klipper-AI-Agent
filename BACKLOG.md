# Backlog

This backlog is organized around the current chosen architecture:

- standalone host daemon
- Moonraker underneath
- supported Mainsail custom-navigation entry in `v1`
- same-origin KlipperAI page at `/klipperai/`
- bounded class-based agent orchestration with read-only tools and optional web search

## Refactoring And Agent Runtime

- [x] Replace the redundant src wrapper with a flat package and focused subpackages
- [x] Split large config/profile/provider modules and introduce composed detectors and proposal strategies
- [x] Preserve the existing behavior tests and the 100% coverage gate
- [x] Add an iterative tool loop with typed tools, bounded calls/time/context and recoverable errors
- [x] Add read-only printer/config/diagnostics tools and configurable hosted web search
- [x] Add Chat/Debug starting context, mode selection and saved context receipts
- [x] Add literal config search, large-file section reads, diagnostic excerpt expansion and component-status groups
- [x] Add explicitly confirmed printer facts/preferences and incident resolutions alongside dated evidence
- [x] Add bounded shutdown-focused reads of current/recent rotated Klippy logs with explicit excerpt provenance
- [x] Show streamed action progress, evidence sources and completed/limited/error states
- [x] Add architecture/sequence diagrams and a regenerable module, symbol, test and import index
- [x] Persist conversations and dated evidence across chats and service restarts
- [x] Add manual-only proposal validation, section comparison and stale-revision rechecks
- [x] Introduce shared domain objects and narrow read-only tool interfaces
- [x] Resume interrupted in-flight investigations after service restart

## Reminders After Investigation And Review Work

- [x] Finish simplifying the surrounding product (frontend and installer), including automated Mainsail and OctoEverywhere regression checks

## Milestone 0: Project Foundation

- [x] Define the initial system architecture
- [x] Scaffold the FastAPI agent service
- [x] Add a minimal embedded UI
- [x] Add deterministic local workflow scaffolding
- [x] Add a deterministic diagnostics rule engine
- [x] Add deployment examples for `systemd` and `nginx`
- [x] Add an interactive Linux installer

## Milestone 1: Diagnostics MVP

- [x] Read recent `klippy.log` directly from the host
- [x] Read recent `moonraker.log` directly from the host
- [x] Add optional `journalctl` collection for Moonraker and Klipper services
- [x] Capture Moonraker and Klipper service status
- [x] Investigate MCU communication/timing/homing shutdowns using pre-stop statistics and confidence-qualified hypotheses
- [x] Correlate retained kernel OOM, USB/CAN, storage and throttling events when an incident clock anchor exists
- [x] Add current Moonraker CPU/memory/thermal observations separately from incident evidence
- [x] Test shutdown rule families, collection limits, missing evidence, agent handoff and persisted reports automated
- [x] Add an opt-in bounded host flight recorder for CPU/process, memory/swap and I/O pressure history
- [x] Add optional `journalctl` collection for broader host services
- [x] Query core Moonraker state for server info, printer status, and config metadata
- [x] Normalize collected context into typed artifacts before LLM calls
- [x] Expand runtime diagnostic rules for heater, homing/endstop, TMC driver, MCU protocol and motion-limit errors, with source evidence and manual investigation guidance
- [x] Return richer evidence blocks in API responses
- [x] Add severity ranking and confidence hints
- [x] Add unit tests for each deterministic diagnostic rule family, including normal messages and false-positive cases

## Milestone 2: UI Session And Embedded Experience

- [x] Improve the embedded chat UI to show findings, evidence, and next actions as distinct cards
- [x] Read printer configuration and recent logs automatically for the agent; the web composer only asks for a question.
- [x] Persist investigation history independently of ephemeral UI sessions
- [x] Stream agent action events and the final response for long-running investigations
- [x] Add explicit error states for Moonraker unavailable, missing provider config, and invalid session
- [x] Add UI affordances for follow-up questions and drill-down analysis

## Milestone 3: Mainsail Integration

- [x] Add a stable same-origin KlipperAI page at `/klipperai/`
- [x] Add a low-coupling Mainsail custom-navigation link that opens KlipperAI
- [x] Add installer support for writing `.theme/navi.json`
- [x] Ensure same-origin routing for `/klipperai/` behind nginx
- [x] Improve the standalone page so it feels more at home inside the printer UI flow
- [x] Retire the optional native drawer patch; keep the left-menu link opening a new tab

## Milestone 4: Moonraker Integration Depth

- [x] Implement a proper Moonraker agent registration flow
- [x] Add Moonraker event subscriptions for printer state changes
- [x] Add file metadata inspection through Moonraker where useful
- [x] Add a database namespace for non-secret assistant metadata
- [x] Define Moonraker-facing methods for session bootstrap and future notifications

## Milestone 5: Config Assistant

- [x] Add an initial config assistant workflow for managed include proposals
- [x] Create a config analysis workflow for active printer configuration
- [x] Detect common config mistakes such as missing includes, invalid pin descriptions, and conflicting sections (static checks; physical pin/firmware validation remains manual)
- [x] Build typed proposal objects for generated config changes
- [x] Support managed include fragments under a KlipperAI-owned directory through manual create/include plans
- [x] Support patch generation against existing config files
- [x] Add conservative static review before proposals are shown; full firmware/hardware validation remains future work
- [x] Add deeper feature-specific generation beyond scaffold-level proposals (parameterized probe, mesh and shaper drafts plus a functional status macro)
- [x] Show proposed-section comparisons in the UI

## Milestone 6: Manual Configuration Review

- [x] Keep all printer configuration edits manual; no apply/approval endpoints
- [x] Associate reviews with config revisions and detect stale proposals
- [x] Store review results only in application-owned memory
- [x] Expand option/version validation and manual verification guidance

## Milestone 7: Provider And Credential Management

- [x] Add secure server-side API key storage outside plain repo files
- [x] Add UI flow for credential setup and rotation
- [x] Add validation checks for provider credentials during setup
- [x] Add model-specific configuration and routing
- [x] Add rate-limit and cost-safety controls

## Milestone 8: Intelligence Quality

- [x] Add richer deterministic rules before broadening agent behavior
- [x] Add prompt and response schemas per workflow instead of one general assistant path
- [x] Add structured citations back to log lines and config sections
- [x] Add recovery playbooks for recurring failure modes
- [x] Build component knowledge dynamically from each printer's saved hardware details, without a fixed board catalog
- [x] Add UI Build/Refresh knowledge, primary-source discovery, versioned documents and local manual downloads
- [x] Extract source-quoted fan connector candidates and require source/revision review before using their pins
- [x] Add read-only local documentation retrieval, conservative fan-port checks and Eddy calibration evidence
- [x] Add fan proposal checks for board revision, MCU identity, alias resolution and pin conflicts
- [x] Broaden hardware bus pin resolution and diagnostic tools for more component families
- [x] Cache firmware-commit-specific references and index PDF text/diagrams
- [x] Add explicit physical connector inventory and live printer/provider validation
- [x] Add config generation templates for high-value features such as macros, probes, and shapers

## Milestone 9: Security And Hardening

- [x] Review local secret storage and file permissions
- [x] Add redaction rules for secrets in logs and configs
- [x] Review nginx and service defaults for safer deployment
- [x] Add authentication assumptions and trust-boundary docs for local deployments

## Milestone 10: Testing And Release Engineering

- [x] Add a Linux CI pipeline for lint, type checks, and tests
- [x] Add integration tests for installer, env generation, and service boot
- [x] Add a smoke test for reverse-proxy routing at `/klipperai/`
- [x] Add example artifacts for known printer failures
- [x] Add versioning, changelog, and release notes conventions
- [x] Add packaging guidance for a one-line remote installer in a future release
- [x] Add fast operator SSH deployment of workspace fixes, build readiness and code rollback; preserve settings, credentials and history

Implementation is ready; Linux CI execution and live printer/provider acceptance
remain to be recorded. See [printer testing](docs/printer-testing.md) and
[release conventions](docs/RELEASING.md).

## Open Product Questions

- [x] Printer config changes remain manual; the application only drafts and reviews them.
- [x] Chat and Debug require an active LLM provider and API key. Without a key, expose setup, connection status and saved information only. Deterministic tools feed the agent; show planned and actual LLM use.
- [x] Should the same custom-navigation approach also be documented for Fluidd? Mainsail only for now
- [x] Use authenticated encrypted provider storage with a separate systemd master credential, TPM binding where available, unified installer/UI rotation, legacy cleanup and explicit recovery limxxxxxxxx xits
                                                                                              
