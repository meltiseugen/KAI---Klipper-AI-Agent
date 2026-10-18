# Architecture

KlipperAI is a standalone async Python daemon on the printer host. Mainsail links
to its same-origin `/klipperai/` UI; Moonraker remains the printer API. The runtime
reads evidence and drafts config proposals. It cannot apply them.

The browser is composed from storage, transport, rendering and application
modules, bundled inline so OctoEverywhere can recover the page into a new tab.
The guided installer composes sourced shell modules. See the
[frontend and installation map](frontend-and-installation.md) for both access
paths and their ownership boundaries.

## Runtime and ownership

```mermaid
flowchart LR
    UI[Browser / Mainsail link] --> API[web: FastAPI + SSE]
    API --> Chat[application: sessions + chat]
    Chat --> Memory[application: investigation memory]
    Memory --> Storage[infrastructure: application-owned SQLite]
    Chat --> Review[config: manual proposal review]
    Chat --> Agent[agent: bounded tool loop]
    Chat --> Offline[workflows: deterministic fallback]
    Agent --> Model[AgentModel protocol]
    Model --> Provider[providers: Responses API]
    Agent --> Registry[ToolRegistry: validate + limit + cache]
    Registry --> Config[config: collector + parser + lookup]
    Registry --> Profile[profile: saved identity]
    Registry --> Diagnostics[diagnostics: collection + rules]
    Registry --> Moonraker[infrastructure: Moonraker reads]
    Registry --> Search[WebSearch protocol]
    Search --> Web[providers: hosted web search]
    Diagnostics --> Host[infrastructure: logs + service status]
    Bootstrap[bootstrap: construction and cleanup] -.-> Chat
```

The [generated dependency graph](generated/dependencies.mmd) shows actual imports
between packages. It is a discovery aid, not the runtime call graph. The generator
rejects cycles between individual modules.

| Package | Owns |
| --- | --- |
| `web` | HTTP validation, HTML/assets, streaming transport |
| `application` | Session validity, investigation memory, routing and proposal review |
| `domain` | Typed evidence, investigations, proposals, messages and repository ports |
| `agent` | Iteration, budgets, tool contracts, request-local evidence and events |
| `providers` | OpenAI protocol, search adapter, single-pass compatibility providers, offline stubs |
| `config` | Includes, parsing, lookup, request targets, proposal strategies |
| `profile` | Saved identity, composed host/hardware/capability/addon detection, INI persistence |
| `diagnostics` | Snapshots and deterministic issue rules |
| `infrastructure` | Moonraker transport and bounded host readers |
| `contracts` | HTTP request/response models and compatibility re-exports |
| `runtime` | Settings and logging |
| `bootstrap` | Composition root and client shutdown |
| `cli` | Profile detection and legacy command-name adapters |
| `workflows` | Offline/config workflow steps and citation helpers |

## Tool-using request flow

```mermaid
sequenceDiagram
    actor User
    participant UI as Browser
    participant API as ChatService
    participant Loop as AgentRunner
    participant Model as AgentModel
    participant Tool as ToolRegistry
    User->>UI: Ask a question
    UI->>API: POST /api/chat/stream
    API->>API: Validate session, load saved investigation and dated memory
    API->>Loop: Request and user-provided artifacts
    Loop->>Tool: Prepare mode-specific starting context
    loop Until answer or configured budget
        Loop->>Model: Conversation + tool definitions
        Model-->>Loop: Tool calls or final JSON answer
        opt Tool requested
            Loop-->>UI: tool_started event
            Loop->>Tool: Validate and execute read-only operation
            Tool-->>Loop: Observation or recoverable error
            Loop-->>UI: tool_completed / tool_error event
            Note over Loop,Model: Next model call includes actual tool output
        end
    end
    Loop-->>API: Answer, findings, sources, activity, status
    API->>API: Review proposals and persist public evidence/outcome
    API-->>UI: result event
    UI-->>User: Answer + sources + expandable activity
```

OpenAI requests default to `AgentWorkflow`. Chat preloads the saved profile and
active config; Debug also preloads live status and bounded log/service evidence.
Both include relevant dated memory. The model then chooses further tools and
can revise its next action after observing evidence. There is no preflight LLM
intent classification in this path. The user sees action summaries, never hidden
reasoning. Responses output items, including encrypted reasoning, are passed
unchanged between model turns within one investigation; `store=false` is used.

Debug also prepares a shutdown report for communication/timing failures through
the optional `ShutdownReader` port. Filesystem, kernel-journal and Moonraker reads
live in infrastructure; pure run/statistics parsing and cause assessments live in
diagnostics. Current host readings stay separate from historical incident evidence.
See [shutdown investigations](shutdown-investigations.md) for bounds and limitations.

`stub` uses deterministic workflows without credentials or network LLM calls.
Setting `agent_enabled=false` retains the older single-pass OpenAI path for
troubleshooting. Neither setting enables writes.

## Tools and evidence

| Tool | Boundary and evidence |
| --- | --- |
| `get_printer_profile` | Saved firmware/hardware/addon summary, explicitly not live state |
| `get_printer_knowledge` | Saved component identities, source readiness and dated confirmed facts |
| `search_printer_knowledge` | Bounded cached source passages with hashes, dates and citations |
| `inspect_fan_ports` | Reviewed board/revision mappings and current config pin owners; physical occupancy remains unconfirmed |
| `inspect_eddy_calibration` | Probe/mesh/temperature/start sections and sourced calibration guidance, with firmware compatibility gaps |
| `investigate_shutdown` | Bounded current/recent rotated Klippy reads, pre-stop statistics and optional kernel correlation; confidence-qualified manual checks |
| `get_printer_status` | Fixed read-only Moonraker methods and known status objects |
| `inspect_config` | File/section index or exact excerpts; optional inactive-file lookup |
| `read_config_file` | Bounded lines from an exact path in the collected tree |
| `collect_diagnostics` | Log tails, optional service/journal reads, deterministic findings |
| `search_config` | Literal pin/option/macro-reference search, active/inactive labels and source lines |
| `read_diagnostic_artifact` | Bounded lines from collected artifact IDs, not arbitrary host files |
| `get_printer_objects` | Fixed sensor/fan/motion/bed-mesh/MCU groups, capped at 24 available objects |
| `search_web` | Public technical query via hosted search, with source URLs |
| `get_gcode_metadata` | Allowlisted parsed metadata for a relative G-code filename or the current job |

Tool caches and fresh config snapshots belong to one request. Successful identical
calls reuse observations within that request; failures can be retried. Public
observations are saved with timestamps and revisions for historical retrieval.
Fresh source cards come from tools and provider annotations, not model-supplied
source objects. Historical context is labeled separately and must be rechecked.

Public context receipts distinguish full, partial, unavailable and omitted sources
and record which were included in a model request. See [agent-modes.md](agent-modes.md)
for preparation, mode switching, large-file expansion and compatibility behavior.

The registry rejects unknown tools and invalid/extra arguments. Per-tool timeouts,
run deadlines, model-step limits, call limits, output-token bounds and context
character limits prevent unbounded loops. Limit/error responses retain collected
findings and source cards and identify incomplete work. Tool errors are observations
the model can recover from. Browser disconnects cancel the run; SSE heartbeats keep
idle proxy connections open.

## State and deployment

The flat layout keeps one importable `klipperai_agent/` package at the repository
root. Hatch includes Python modules, templates and static assets in the wheel.
CLI names remain `klipperai-agent` and `klipperai-detect-profile`; older
`klippyai-*` commands adapt environment variables into the canonical package.

Sessions are ephemeral. `thread_id` identifies a durable investigation stored in
`data_dir/investigations.sqlite3`. Server history takes precedence over browser
history for existing investigations. Relevant historical evidence can be supplied
to a new chat alongside explicitly user-confirmed facts, preferences and incident
resolutions. The Printer memory panel owns confirmation; model tools cannot write
these records. Current config/status still require fresh reads. Provider HTTP
clients are pooled and closed with the application lifespan.

The application lifespan owns a recovery worker for interrupted investigations.
Public requests and dated tool evidence are checkpointed under renewable SQLite
leases. Recovery reconstructs a new bounded run with fresh reads; hidden reasoning
and provider conversation state never enter storage. A completed turn and removal
of its pending checkpoint commit atomically. See [investigations](investigations.md)
for recovery timing, retry bounds, deletion and browser behavior.

The application lifespan also owns one Moonraker Unix-socket agent connection.
Infrastructure identifies it, subscribes to fixed printer fields, reconnects and
merges bounded observations in `domain/moonraker.py`. Application-owned extension
methods expose public capabilities/status and ephemeral session bootstrap. A
session-protected SSE endpoint sends the latest observation to UI badges at most
once per second. The model's status tools still make fresh reads. Moonraker's
`klipperai.integration` database item stores only fixed public capabilities; it
is separate from investigations, credentials and sessions. See
[Moonraker integration](moonraker-integration.md) for protocol and ownership details.

Component knowledge lives separately in `data_dir/knowledge.sqlite3`. The user
builds/refreshes documentation for their saved components through the UI. Public
product details drive hosted search; downloaded text supplies quoted connector
candidates for source/revision review. There is no built-in board catalog. Changed
documents, mappings or wiring invalidate connector review. Model tools receive
only a read-only port. Fan proposals receive additional hardware checks. See
[printer knowledge](printer-knowledge.md) for identity confirmation, source
versions, local manuals, download limits and firmware compatibility boundaries.

Proposals undergo static review and section comparison. Users edit config files
manually; there are no apply/approval endpoints or write tools. Revalidation reads
the active config and marks changed revisions stale. See
[investigations.md](investigations.md) for lifecycle, storage limits and endpoints.

The supported host is Python 3.10+, FastAPI, Pydantic v1 and httpx. The new loop
does not require LangGraph, an agents framework, a search SDK or Rust extensions.
API keys stay in private server storage, with environment defaults before the first
provider-settings save. Provider policies activate on manual service restart; one
persistent usage ledger guards all model paths. See [providers.md](providers.md).
The app assumes the existing trusted
local deployment/proxy boundary; UI sessions are not account authentication.
Credential redaction protects collected text, model inputs, public outcomes and
saved history. See [security.md](security.md) for its limits and storage/proxy
assumptions. Hosted search requires a compatible OpenAI model and uses provider credits.

Protocol references: [function calling](https://developers.openai.com/api/docs/guides/function-calling),
[web search](https://developers.openai.com/api/docs/guides/tools-web-search), and
[Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create).
