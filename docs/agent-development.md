# Extending the agent

## Add a tool

1. Add a class in `klipperai_agent/agent/tools/` implementing `Tool[Arguments]`.
   Define `name`, `label`, `description`, and a `ToolArguments` subclass. Extra
   arguments are forbidden. Use bounded fields and narrow, read-only operations.
2. Implement `execute(arguments, context)`. Receive dependencies through
   `ToolContext`; keep per-investigation observations there. Return JSON-compatible
   evidence or an explicit `error`. Do not return raw exceptions or credentials.
3. Register it in `AgentWorkflow.ainvoke`. Conditional tools must be absent from
   both dispatch and advertised schemas when disabled.
4. Add source citations to `context.citations` when evidence has a real file/line
   or retrieved URL. Do not let the model construct trusted source cards.
5. Test argument rejection, success, missing evidence, bounded output and a
   multi-step investigation where the next model call uses the observation.
6. Regenerate the project map and run coverage, lint and type checks.

The runner owns time/call/step budgets. The registry owns validation, timeout,
deduplication and result-size bounds. A tool should not start its own autonomous
loop. The hosted search adapter makes one bounded search request as a capability.

Log/config search tools demonstrate literal matching, bounded continuation and
cached excerpt expansion. Log filesystem reads go through the narrow `LogReader`
port; model inputs select inventory IDs, never host paths. See
[read-only search contracts and limits](log-and-config-search.md). Keep the
read-only boundary enforced in schemas, dispatch, ports and adapters; prompt text
alone is insufficient.

Starting context is built by `agent/starting_context.py` before the first model
call, under the same run deadline. Mode policy belongs there, not in individual
tools. New tools automatically receive public receipts through the registry;
return `truncated` and a concise `context_notes` when evidence is partial. See
[agent-modes.md](agent-modes.md) for the Chat/Debug policies and expansion limits.

The `investigate_shutdown` tool demonstrates a composed `ShutdownReader` port,
pure incident/statistics analysis, bounded host reads and confidence-qualified
manual troubleshooting. See [shutdown investigations](shutdown-investigations.md)
for its evidence semantics, limitations and regression tests.

`inspect_component` composes the same read-only knowledge/config/printer ports for
fixed accelerometer, probe, driver, temperature and filament families. It caps
available status objects and returns manual checks with source citations. Physical
inventory, source review, diagram-note writes and validation triggers belong to
session-protected user controls, never model tool arguments. See
[hardware knowledge](hardware-knowledge.md).

`get_gcode_metadata` uses the narrow `FileMetadataReader` port. Filenames must be
relative to Moonraker's G-code root; omitted filenames query the current job.
The HTTP adapter filters metadata to bounded scalars, excluding thumbnails and
raw G-code. Slicer estimates are evidence about a file, not the current machine
configuration or measured print time. See [Moonraker integration](moonraker-integration.md).

## Add a model or search provider

Implement `AgentModel.respond(conversation, tools, *, response_format=None) -> ModelTurn` or
`WebSearch.search(query) -> SearchResult`. Keep provider-specific wire parsing in
`providers/`. Inject adapters through `bootstrap/container.py`. Preserve opaque
reasoning/state items in the provider conversation; do not display them as activity.
Return validated source URLs from the search adapter. The runner accepts typed
`InvestigationRequest` and returns `InvestigationResult`; the compatibility
workflow boundary alone translates legacy dictionaries.

`response_format` is an application-selected strict JSON schema. Adapters should
forward it through their provider's structured-output protocol; the runner also
validates locally. Workflow contracts and citation resolution live in
`agent/response_contracts.py` and `claim_citations.py`. See
[intelligence quality](intelligence-quality.md) before changing these boundaries.

Use `httpx.MockTransport` in tests; no API key is needed for the test suite. Verify
tool-call IDs, unknown tools, refused/incomplete responses, malformed final JSON,
and resource cleanup. A real provider smoke test is separate and requires a valid
server-side credential and compatible model.

## Configuration

With `llm_provider: openai`, the agent and search default to enabled. Under `[agent]`:

```ini
agent_enabled: true
web_search_enabled: true
web_search_domains:  # optional comma-separated domains, without https://
agent_max_steps: 8
agent_max_tool_calls: 12
agent_tool_timeout_seconds: 30
agent_run_timeout_seconds: 180
agent_max_context_chars: 120000
agent_max_result_chars: 16000
agent_max_output_tokens: 6000
```

Disable web search to inspect only local evidence. Disabling the agent selects the
existing single-pass OpenAI workflow for compatibility. An API key is required
for both paths. Deterministic checks feed the model. Restart the service after editing the config. Provision
API keys through the secure installer or Provider settings; see
[encrypted credentials](credential-storage.md). A systemd master credential is
required to persist keys; never put them in this config file.

## HTTP contract

`POST /api/chat` still returns a `ChatResponse` JSON object. The additive fields
`agent_events` and `agent_status` expose activity and completed/limited/error state.
Requests also accept `mode` (`chat` by default or `debug`). Responses include
`mode` and `context_included`; bootstrap advertises supported `agent_modes`.

`POST /api/chat/stream` accepts the same body, validates the session before opening
the stream, and emits SSE `agent`, `result`, or `error` events. Heartbeat comments
carry no data. `result` contains the full `ChatResponse`, including citations and
proposals. A transport error never exposes internal exception text. Client
disconnect cancels the producer.

The UI stores final activity with each browser conversation. Progress updates are
action descriptions, not model reasoning. Source cards use textContent and HTTP(S)
links. Config proposals pass through `ProposalReviewService` and remain manual-only.
The UI restores durable investigation history and offers read-only proposal rechecks.
See [investigations.md](investigations.md) for memory settings and ownership.
See [printer-knowledge.md](printer-knowledge.md) for dynamic component research,
bounded public-document downloads, local retrieval and fan proposal hardware checks.
Knowledge refresh is a session-protected UI operation; the agent receives only
the `KnowledgeReader` port and cannot trigger downloads or save identities.

## Remaining boundaries

No general URL fetcher, filesystem path reader, shell tool or printer control tool
is registered. Prompt instructions treat logs/config/web text as untrusted data.
Credential redaction runs at collection, tool, prompt, result and persistence
boundaries. New tools must preserve that behavior and redact before clipping
evidence. Keep transport session IDs and provider protocol envelopes intact.
Redaction is best effort, not complete sanitization. The API assumes the existing
trusted local printer UI or authenticated proxy boundary; sessions are not user
authentication. See [security.md](security.md). Hosted search uses provider credits.
