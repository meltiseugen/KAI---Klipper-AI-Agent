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

## Add a model or search provider

Implement `AgentModel.respond(conversation, tools) -> ModelTurn` or
`WebSearch.search(query) -> SearchResult`. Keep provider-specific wire parsing in
`providers/`. Inject adapters through `bootstrap/container.py`. Preserve opaque
reasoning/state items in the provider conversation; do not display them as activity.
Return validated source URLs from the search adapter. The runner accepts typed
`InvestigationRequest` and returns `InvestigationResult`; the compatibility
workflow boundary alone translates legacy dictionaries.

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
existing single-pass workflow for compatibility. `stub` always uses offline
deterministic workflows. Restart the service after editing the config. Keep the
API key in `KLIPPERAI_OPENAI_API_KEY`, outside this file.

## HTTP contract

`POST /api/chat` still returns a `ChatResponse` JSON object. The additive fields
`agent_events` and `agent_status` expose activity and completed/limited/error state.

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

## Remaining boundaries

No general URL fetcher, filesystem path reader, shell tool or printer control tool
is registered. Prompt instructions treat logs/config/web text as untrusted data.
They do not constitute complete secret redaction; broader redaction and deployment
authentication remain separate backlog items. The API assumes the existing
trusted local printer UI boundary. Hosted search uses provider credits.
