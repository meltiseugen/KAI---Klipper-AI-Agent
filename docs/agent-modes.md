# Chat and Debug modes

The tool-using agent has two starting-context policies. Both use the same runner,
model, read-only tools and manual proposal review.

| Mode | Starting evidence |
| --- | --- |
| Chat (default) | Saved printer profile, active config tree, conversation and relevant dated evidence |
| Debug | Chat context plus live printer status, bounded current log tails and configured service diagnostics |

Chat does not automatically collect logs or live status. It can use diagnostic
tools when the question requires them. Debug prepares evidence before the first
model call. Host log exclusions, configured tail lengths and systemd collection
settings still apply. Missing evidence is visible and does not prevent the model
from answering with other evidence.

Choose the mode beside the question field. Switching preserves the conversation
and changes the next request. It does not retract earlier messages or diagnostic
observations already present in history or recalled evidence. New chats default
to Chat. The choice is retained in browser storage, and each saved turn records
its mode so another browser can restore the last used mode.

The selector is enabled when bootstrap advertises `agent_modes: ["chat", "debug"]`.
The `stub` and `agent_enabled=false` compatibility workflows retain their existing
context selection; they do not implement these policies. The UI explains this and
disables the selector. Explicit Debug requests to these workflows return HTTP 400.
Omitting `mode` defaults to `chat`; unknown values are rejected. Both JSON and SSE
chat endpoints accept the mode.

## What is included

Each answer has an expandable **Context included** receipt. It lists starting
context and later tool results, collection timestamps, full/partial/omitted or
unavailable evidence, and whether it was included in a model request. This records
handoff to the model adapter, not confirmation of receipt from an external provider.
If a run stops before its first model call, collected items are marked not sent.
Receipts are saved and restored with the conversation.

The root config and its includes are supplied as full files when they fit. Larger
files/trees fall back to section indexes or explicit omissions. The production
collector indexes at most 100 files and initially retains 24,000 characters per
file. Config tools can expand a known file up to 1,000,000 characters to inspect
sections beyond that initial excerpt. Expansion verifies the original digest;
a manual edit during the request requires a new question to refresh the evidence.
The model cannot turn a path argument into an arbitrary filesystem read.
Files outside the root include tree require explicit inactive lookup and are not
preloaded. The tree is the on-disk configuration, which can differ from what
Klipper currently has loaded.

Diagnostics use bounded log tails rather than a guaranteed time interval. Previews
preserve selection metadata and the newest text; artifact IDs and excerpt line
counts allow targeted expansion. The response includes up to 12 artifacts and
reports omissions. `read_diagnostic_artifact` addresses the collected excerpt,
so its line numbers are not original log file line numbers. It cannot search older
or rotated logs. Large results are marked partial.

For communication/timing/shutdown questions or matching diagnostic evidence, Debug
also runs [the shutdown investigator](shutdown-investigations.md) before the first
model call. Its separate bounded read searches current/recent rotated Klippy logs,
summarizes pre-stop statistics and queries time-correlated kernel events when a
usable clock anchor exists. It honors log exclusions and collection switches;
general log-tail line settings do not restrict this dedicated byte-bounded search.
Current host readings remain explicitly separate from historical incident evidence.

The starting-context budget reserves room for follow-up tools and the response.
Preparation shares the run deadline, and individual reads use the tool timeout.
Preparation performs a fixed set of reads outside the model-selected tool-call
budget. Identical successful reads reuse request-local observations; missing
evidence can be retried. Cancellation propagates through preparation and tools
on supported Python 3.10 hosts.

## Knowledge and permissions

Saved profile data describes configured identity. Recalled observations retain
their original timestamps and revisions. Prior answers and hypotheses are not
promoted into confirmed printer facts. The **Printer memory** panel lets the user
explicitly confirm facts, preferences and incident resolutions, optionally linking
dated observations. Both modes receive relevant confirmed entries alongside
historical evidence. Interrupted requests retain their selected mode and resume
with fresh starting context after service restart. See [investigations and memory](investigations.md).

All modes remain read-only toward the printer. No tool can run shell commands,
move the printer, change heaters, restart services or apply a proposal. Configs,
logs and prior messages are treated as untrusted evidence. This is not complete
secret redaction; see [agent-development.md](agent-development.md).

## Implementation and checks

- `domain/context.py`: mode and public receipt contracts.
- `agent/starting_context.py`: deterministic preparation and config budgeting.
- `agent/registry.py`, `agent/deadline.py`: validation, receipts, caching and deadlines.
- `agent/tools/config_search.py`: literal pin/option/macro-reference search.
- `agent/tools/diagnostics.py`: bounded expansion of known diagnostic artifacts.
- `agent/tools/objects.py`: fixed sensor/fan/motion/bed-mesh/MCU status groups.
- `application/chat.py`, `contracts/api.py`: request propagation and saved outcomes.
- Browser application/store/shell/investigation modules: selector and receipt display.

`test_agent_modes.py` covers preparation, failures, budgets, large files, tool
validation and saved mode switches. HTTP tests cover both endpoints. JavaScript
mode tests cover selection, in-flight locking, request history, restoration and
text-only receipts. These offline checks do not establish live provider answer
quality, real printer behavior or rendered browser layout.
