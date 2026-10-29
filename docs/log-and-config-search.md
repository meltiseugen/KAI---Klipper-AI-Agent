# Read-only log and configuration search

The LLM can choose these tools while investigating a question. Chat and Debug
still preload configuration and recent logs automatically; no pasting or uploading
is required. Search results feed the agent and retain source evidence.

## Capabilities

| Tool | Purpose and scope |
| --- | --- |
| `list_logs` | List up to 16 eligible current/recent logs from the configured directory. Returns opaque `log_id` values, filenames, sizes and modification dates. `refresh: true` refreshes references after rotation. |
| `search_logs` | Find literal text with surrounding lines in up to four selected log windows. Default selection searches current logs; `include_rotated: true` admits recent rotations. Explicit `log_ids` can select listed rotations directly. |
| `read_log_excerpt` | Read more lines around a search match using its cached `excerpt_id`. It does not open another file. |
| `search_diagnostic_artifacts` | Find text in previously collected diagnostic artifact IDs, including available service/journal excerpts. It runs no new commands or filesystem reads. |
| `search_config` | Find text across the collected config tree, optionally filtered by exact collected `path` and exact `section`. `whole_word` distinguishes identifiers such as `PA1` from `PA10`. |
| `inspect_config` / `read_config_file` | List collected files/sections, inspect a section or read a bounded line range from an exact collected reference. |
| `collect_diagnostics` / `read_diagnostic_artifact` | Collect configured diagnostics or expand an existing diagnostic excerpt. System reads use fixed application-owned commands and unit names. |

Search tools accept literal `query`, `case_sensitive`, `whole_word`, `context_lines`
(0–4), `max_matches` (1–20), and match `offset` (0–10,000). Patterns are escaped
internally: model text is never a shell command or a user-defined regular expression.
The response includes surrounding source text, `match_line`, matched-file identity,
`total_matches` within the searched scope and `next_offset` when more matches exist.
Character limits can shorten individual lines and the number of matches in a page.

Configuration matches include comments and macro references. A text match does not
establish that a setting is effective or a macro executes. Additional unincluded
files remain explicitly marked inactive. Missing/changed files remain evidence gaps.

## Log windows and continuation

1. The agent calls `list_logs` or lets `search_logs` discover eligible current logs.
2. It searches a literal error, MCU name or event using returned log IDs. A result
   contains `windows`, byte ranges, observation timestamps and cached excerpt IDs.
3. It uses `read_log_excerpt` with an excerpt ID and line range to read surrounding
   evidence. Cached evidence remains the same even if a current file later appends.
4. To search further back in an **uncompressed** file, it selects exactly one log ID
   and passes that window's `next_before_byte`. Match offsets restart at zero for
   a different window. Within the same window, `offset: next_offset` continues the
   matching lines. Repeated identical windows are cached during the investigation.
5. After rotation/truncation, it refreshes inventory and searches a new reference.
   Refresh invalidates old excerpt IDs and does not reset the cumulative read budget.

Each raw window is at most **256 KiB**. The first incomplete line at a byte boundary
is dropped. Backward cursors overlap that boundary sufficiently to recover a normal
record crossing windows; a record larger than a whole window may remain unavailable.
Raw appends after the inventory's size snapshot are excluded. Changes in place are
not a verified historical snapshot; a cached window records what was actually read.

Compressed `.gz` logs support a final window only. They have an **8 MiB compressed
input and decompressed-output ceiling**, and changes after inventory require a refresh.
No arbitrary compressed-file seek or unbounded decompression is available.

The new log search tools share an investigation allowance of **eight cached windows**
and **12 MiB reserved read/decompression work**. Failed or cancelled reads still
consume allowance. A compressed read conservatively reserves its entire 8 MiB
decompression allowance, even for a small compressed file. Separate existing
diagnostic/shutdown tools retain their own documented limits.

Config file expansion keeps at most **4,000,000 decoded characters** per investigation
across expanded references. Existing individual file, document-count, initial excerpt,
model-context and tool-result bounds also apply. No new runtime dependencies were added.

## Citation semantics

- A window read from the start of a file can use `line_basis: file`. A tail/older
  window starting later uses `line_basis: excerpt`; its numbers are window-local.
- Compressed file lines refer to decompressed text. Byte ranges for compressed
  windows describe decompressed data, not offsets into the `.gz` file.
- The digest identifies the **redacted window**, not the complete original file.
  Collection time records the read, not necessarily the time a log event occurred.
- Clipped lines and omitted files/windows are labeled. No matches means only that
  the searched text did not contain the query; it never proves that a fault did not
  happen elsewhere in a file or in older/omitted logs.

## Enforced read-only boundary

The model has **no edit, write, delete, upload, shell, G-code, motion, heater or restart
operation**. Tool schemas reject extra mutation arguments. Unknown tool names fail
closed in `ToolRegistry`.

Filesystem log tools receive only the `LogReader` protocol: inventory and bounded
window reads. Model arguments cannot contain a host path, download URL, command,
filename glob, open mode or read-size override. Selected IDs must belong to the
current request's inventory. Config paths must exactly match collected references.

The log adapter opens with `O_RDONLY`, checks file identity and regular-file type,
rejects symlinks/hardlinks/redirection, and uses no-follow/nonblocking flags where
the operating system supports them. It rejects disappearance, truncation and unsafe
file substitutions with public errors. Existing excluded-log names/globs cover
their rotations too. Disabling `collect_host_logs` removes filesystem log tools
from both advertised schemas and dispatch. Credential redaction occurs before
searchable log text or citations reach the model.

KlipperAI still persists public investigation outcomes/evidence in its own application
storage. That is application bookkeeping, not a model-controlled file-writing tool.
Configuration proposals remain text for the user to review and edit manually.

## Verification

`test_log_reader.py`, `test_agent_search.py` and `test_text_search.py` cover real-file
reads, bounded decompression, paging, changed/missing sources, redaction, strict
arguments, disabled tools, context/citations, unchanged file bytes and a multi-step
agent that uses the observations. Native Unix symlink/FIFO/hardlink tests run on
Unix; Windows tests also exercise fail-closed identity and redirection checks.
These fixtures do not establish live printer/provider behavior or print-time
performance on the target host.
