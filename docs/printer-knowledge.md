# Printer knowledge

Knowledge is built for the hardware in each user's printer details. There is no
built-in board catalog or manufacturer allowlist. A Creality KE, Qidi Plus 4,
SV08, custom printer or unfamiliar controller uses the same research path.
This makes the workflow available for any model; it does not guarantee that
public documentation exists or establish which board revision a printer contains.

## Build and refresh

1. Open **Printer knowledge** in the chat header. The initial component names
   come from the saved printer profile.
2. Enter the printer model and each component's manufacturer, exact model,
   hardware revision, Klipper MCU name and connection. Confirm the identities you
   have checked. Use **Add component** for additional boards, probes or devices.
   Uncertain information can stay blank; don't infer a board from the printer name.
3. Record the installed firmware fork/version and confirmed wiring details.
   Optionally supply up to three public HTTPS documentation URLs per component.
4. Choose **Build printer knowledge**. With the OpenAI agent and web search enabled,
   the service searches for primary manufacturer documentation for these identities.
   Supplied URLs take precedence over discovery. The UI shows progress and partial failures.
5. If fan connector candidates are found, read their source links and exact quotes.
   Confirm that the sources and mappings match the actual board and revision with
   **I verified these sources and connector mappings**. Search matches alone are
   not trusted pin assignments.
6. Use **Refresh knowledge** after hardware/documentation changes. Changed document
   content, candidate mappings, MCU or connection makes the previous connector
   review stale. Fetching unchanged content only updates its retrieval date.

Saving details changes only KlipperAI application storage, not `klipperai.cfg` or
printer files. A change in the saved profile detected on application restart
requires the user to recheck and save the knowledge identities. Component names
are unique lowercase identifiers; `all` is reserved for document search.

Automatic discovery and extraction use the configured provider and may consume
credits. Search receives manufacturer, model, revision, printer model and firmware
flavor/version. Extraction receives component identity and a bounded public-source
excerpt. Private configs, logs, MCU assignments and wiring notes are excluded from
these research calls. Use public product names in those identity fields.
Normal chat/debug context follows its own documented context policy.

With search/the agent disabled or the offline provider selected, users can still
save details and cache documents from supplied public URLs. Automatic discovery
and connector extraction are unavailable in that configuration. Cached evidence
remains readable offline. Model-selected knowledge tools require the tool-using agent.

## Evidence and recommendations

Chat and Debug preload a bounded summary of identities, documentation readiness
and dated user facts. Read-only tools retrieve details as needed:

| Tool | Evidence |
| --- | --- |
| `get_printer_knowledge` | Saved identities, connection/MCU mapping, confirmation state and dated notes |
| `search_printer_knowledge` | Up to three local passages, with source URL, date, hash and line number; any saved component name or `all` |
| `inspect_fan_ports` | Reviewed connector mappings compared with the active include tree, MCU-qualified pins, aliases, multi-pin outputs and existing owners |
| `inspect_eddy_calibration` | Eddy-family identity, firmware, probe/temperature/mesh/start configuration, saved calibration markers and local passages |

Documents are scoped to the component identity and revision. Removing/changing an
identity excludes its former documents. Search results and extracted mappings are
untrusted candidates: extraction must return a verbatim passage containing both
the connector label and MCU pin. Conflicting connector mappings block review.
The user reviews source suitability because a matching title, model response or
recent download cannot establish the exact installed hardware.

For "add a fan", the agent can return an actual MCU-qualified pin and illustrative
`fan_generic` section only after source review, exact identity/revision confirmation
and complete pin-ownership checks. In-use connectors show their owners. Others are
labelled **unused in configuration; physical occupancy unconfirmed**. Check the
physical connector, voltage/current limits and fan purpose before manual editing.
`heater_fan`, `controller_fan` and `temperature_fan` have different semantics.

Missing includes, unresolved aliases, unsupported pin syntax, uncertain hardware
bus reservations or conflicting MCU assignments prevent a free-port claim. Config
expansion is capped at 2,000,000 characters overall with the existing per-file
limit. Inactive files do not count as active pin owners. Files on disk may differ
from the configuration loaded by firmware. Alias/bus checks follow Klipper's
[board pin implementation](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/board_pins.py)
and [bus implementation](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/bus.py).
Fan proposals also undergo deterministic hardware checks before display, including
duplicate proposed pins. Printer changes always remain manual.

The Eddy helper investigates probe errors, mesh shape, first-layer height and
thermal drift without running calibration. It checks MCU/transport, matching
probe/temperature sections, offsets, macros and saved calibration markers. A
Moonraker read compares reported and saved firmware versions. Local guides are
not automatically matched to the installed firmware commit: missing compatibility
evidence requires further research. Other probes use the generic knowledge/config
tools; a dedicated diagnostic helper is not implied for every component family.

## Storage, downloads and limits

`data_dir/knowledge.sqlite3` is application-owned, separate from investigations
and scoped by printer identity. It stores details, user facts, quoted candidates,
review fingerprints, original documents and readable companion text. Deleting a
conversation does not delete this knowledge. Only public outcomes/evidence are
stored; hidden model reasoning is not persisted.

The UI links source documents and provides **Download cached copy**. PDF, PNG and
JPEG originals are retained for viewing/download; their text/diagrams are not
automatically indexed. Readable HTML/text provides local search and extraction.
GitHub file-viewer links are converted to the corresponding raw document URL.
Candidate extraction examines at most 45,000 characters per readable source and
does not infer mappings from unprocessed diagrams.

Downloads use public HTTPS only. Every redirect is checked, every resolved address
must be public, and the connection is pinned to a checked IP while retaining the
original TLS hostname. Credentials, cookies, proxies and private/local destinations
are not used. Downloaded scripts are never executed. HTML scripts/styles are
excluded from searchable text. Original downloads use attachment disposition.

Limits: 12 components, 3 sources each, 16 connector candidates per source,
8 MiB per download (512 KB for readable text), 300,000 indexed characters per
source, two stored versions per source, and a 128 MiB/72-version cache per printer.
HTTP timeout is 20 seconds, each fetch is bounded to 30 seconds, discovery to
90 seconds and extraction to 60 seconds. A whole sequential refresh is bounded to
10 minutes. Failures retain prior successful copies; changed sources invalidate
old connector review even if extracting their replacements fails.

Concurrent refresh requests share one job. Details/reviews are locked while it
runs, and revision checks prevent another window silently overwriting changes.
Successful component refreshes prune superseded sources. Closing the panel stops
UI polling while the server job continues. Shutdown cancels it; cached documents
survive, but interrupted jobs require a new refresh after restart.

## Implementation and validation

- `domain/knowledge.py`: identity, document and mapping records; storage/research ports.
- `knowledge/`: identity scoping, quoted evidence, retrieval, pin checks and diagnostics.
- `providers/knowledge.py`: public identity discovery and candidate extraction.
- `application/knowledge.py`: build/refresh, concurrency and source review.
- `infrastructure/knowledge.py`, `documentation.py`, `public_docs.py`: bounded cache and public downloads.
- `agent/ports.py`, `agent/tools/knowledge.py`: read-only model boundary.
- `web/knowledge.py`, `web/static/knowledge.js`: session-protected UI operations.
- `tests/test_knowledge*.py`, `tests/knowledge-ui.test.mjs`: unfamiliar models,
  evidence changes, private-network blocking, conflicts, persistence and UI flows.

Adding a different board does not require editing Python or a catalog. Enter its
details and research its documentation. Missing or ambiguous evidence remains a
gap. Remaining work includes PDF/diagram extraction, firmware-commit-specific
reference selection, more bus/pin formats, physical connector inventories, more
diagnostic families and live printer/provider validation.
