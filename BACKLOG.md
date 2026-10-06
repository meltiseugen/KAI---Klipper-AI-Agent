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
- [x] Show streamed action progress, evidence sources and completed/limited/error states
- [x] Add architecture/sequence diagrams and a regenerable module, symbol, test and import index
- [ ] Validate tool selection and answer quality against a real printer and live provider
- [x] Persist conversations and dated evidence across chats and service restarts
- [x] Add manual-only proposal validation, section comparison and stale-revision rechecks
- [x] Introduce shared domain objects and narrow read-only tool interfaces
- [ ] Resume interrupted in-flight investigations after service restart

## Reminders After Investigation And Review Work

- [ ] Finish simplifying the surrounding product (frontend and installer)
- [ ] Measure whether the agent solves printer problems using realistic investigations

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
- [ ] Add optional `journalctl` collection for broader host services
- [ ] Query core Moonraker state for server info, printer status, and config metadata
- [ ] Normalize collected context into typed artifacts before LLM calls
- [ ] Expand deterministic detections for common Klipper problems
- [ ] Return richer evidence blocks in API responses
- [ ] Add severity ranking and confidence hints
- [ ] Add unit tests for each deterministic diagnostic rule family

## Milestone 2: UI Session And Embedded Experience

- [ ] Improve the embedded chat UI to show findings, evidence, and next actions as distinct cards
- [ ] Add artifact upload support for pasted files and drag-and-drop log snippets
- [x] Persist investigation history independently of ephemeral UI sessions
- [x] Stream agent action events and the final response for long-running investigations
- [ ] Add explicit error states for Moonraker unavailable, missing provider config, and invalid session
- [ ] Add UI affordances for follow-up questions and drill-down analysis

## Milestone 3: Mainsail Integration

- [x] Add a stable same-origin KlipperAI page at `/klipperai/`
- [x] Add a low-coupling Mainsail custom-navigation link that opens KlipperAI
- [x] Add installer support for writing `.theme/navi.json`
- [ ] Ensure same-origin routing for `/klipperai/` behind nginx
- [ ] Validate the full-page KlipperAI route on common desktop and tablet layouts
- [ ] Improve the standalone page so it feels more at home inside the printer UI flow
- [ ] Decide whether the optional native drawer patch still earns its maintenance cost

## Milestone 4: Moonraker Integration Depth

- [ ] Implement a proper Moonraker agent registration flow
- [ ] Add Moonraker event subscriptions for printer state changes
- [ ] Add file metadata inspection through Moonraker where useful
- [ ] Add a database namespace for non-secret assistant metadata
- [ ] Define Moonraker-facing methods for session bootstrap and future notifications

## Milestone 5: Config Assistant

- [x] Add an initial config assistant workflow for managed include proposals
- [ ] Create a config analysis workflow for active printer configuration
- [ ] Detect common config mistakes such as missing includes, invalid pins, and conflicting sections
- [x] Build typed proposal objects for generated config changes
- [ ] Support managed include fragments under a KlipperAI-owned directory
- [ ] Support patch generation against existing config files
- [x] Add conservative static review before proposals are shown; full firmware/hardware validation remains future work
- [ ] Add deeper feature-specific generation beyond scaffold-level proposals
- [x] Show proposed-section comparisons in the UI

## Milestone 6: Manual Configuration Review

- [x] Keep all printer configuration edits manual; no apply/approval endpoints
- [x] Associate reviews with config revisions and detect stale proposals
- [x] Store review results only in application-owned memory
- [ ] Expand option/version validation and manual verification guidance
- Printer writes, automatic restarts and rollback execution are outside the current product scope.

## Milestone 7: Provider And Credential Management

- [ ] Add secure server-side API key storage outside plain repo files
- [ ] Add UI flow for credential setup and rotation
- [ ] Add validation checks for provider credentials during setup
- [ ] Add more providers beyond OpenAI
- [ ] Add model-specific configuration and routing
- [ ] Add rate-limit and cost-safety controls

## Milestone 8: Intelligence Quality

- [ ] Add richer deterministic rules before broadening agent behavior
- [ ] Add prompt and response schemas per workflow instead of one general assistant path
- [ ] Add structured citations back to log lines and config sections
- [ ] Add recovery playbooks for recurring failure modes
- [ ] Add printer-profile awareness for common hardware classes
- [ ] Add config generation templates for high-value features such as macros, probes, and shapers

## Milestone 9: Security And Hardening

- [ ] Review local secret storage and file permissions
- [ ] Restrict host access tools to the minimum required surface
- [ ] Add redaction rules for secrets in logs and configs
- [ ] Add request size limits and artifact truncation rules
- [ ] Review nginx and service defaults for safer deployment
- [ ] Add authentication assumptions and trust-boundary docs for local deployments

## Milestone 10: Testing And Release Engineering

- [ ] Add a Linux CI pipeline for lint, type checks, and tests
- [ ] Add integration tests for installer, env generation, and service boot
- [ ] Add a smoke test for reverse-proxy routing at `/klipperai/`
- [ ] Add example artifacts for known printer failures
- [ ] Add versioning, changelog, and release notes conventions
- [ ] Add packaging guidance for a one-line remote installer in a future release

## Open Product Questions

- [x] Printer config changes remain manual; the application only drafts and reviews them.
- [ ] How much of the assistant should be accessible without any external LLM provider configured?
- [ ] Should a future native shell integration target Mainsail only, or keep Fluidd parity close behind?
- [ ] What is the right long-term secret storage method for a local appliance-style install?
- [ ] How should multi-printer hosts be modeled in the agent and UI?
- [ ] Is a true native Mainsail drawer still worth carrying after the low-coupling `/klipperai/` flow is in use?
