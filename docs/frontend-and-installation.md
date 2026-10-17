# Frontend and installation map

Start here for browser behavior, Mainsail access, or the optional OctoEverywhere
patch. Python services and investigation ownership remain in
[architecture.md](architecture.md) and [investigations.md](investigations.md).

## Browser composition

`web/app.py` reads `web/static/scripts.json` in order and bundles the scripts
and CSS into the page. There is no JavaScript build step or npm runtime dependency.
Root, `/embed`, and `/direct` serve the same self-contained, uncached page.
This is deliberate: OctoEverywhere's navigation helper can fetch `/direct` and
write that HTML into a popup without relying on separate asset requests.

| File under `klipperai_agent/web/static/` | Responsibility |
| --- | --- |
| `embed.js` | Construct the application, store, transport and view |
| `chat-application.js` | Bootstrap, restore, select, submit, delete and recheck; one operation at a time |
| `store.js`, `conversation.js` | Browser history, draft persistence, migration and value normalization |
| `transport.js` | Public API prefix, ephemeral sessions, one retry on expired sessions, HTTP operations |
| `agent.js` | SSE decoding and rendering public tool activity and next actions |
| `investigation.js` | Saved-turn conversion, dated evidence and manual review cards |
| `message-view.js`, `markdown.js` | Message cards, source citations and text-only Markdown rendering |
| `shell-view.js` | Chat history, composer, status badges and mobile navigation |

```mermaid
flowchart LR
    Entry[embed.js] --> App[ChatApplication]
    App --> Store[ConversationStore]
    Store --> Local[Browser drafts]
    App --> View[ShellView + MessageView]
    App --> HTTP[ChatTransport]
    HTTP --> Stream[ChatStreamReader]
    HTTP --> API[Chat + investigation APIs]
```

The sidebar displays conversation history. It does not infer printer call graphs
from message text. Model text is rendered as text nodes, never interpreted as HTML.
The transport owns all session retry logic; renderers do not fetch data.

The composer mode selector updates a per-conversation preference. Requests carry
that mode, and saved answer receipts render under **Context included**. Switching
keeps history; in-flight operations lock the selector. See [agent-modes.md](agent-modes.md).

## Access paths

```mermaid
flowchart LR
    Mainsail[Mainsail navi.json] --> Local[nginx /klipperai/]
    Local --> Backend[KlipperAI on loopback]
    Remote[OctoEverywhere portal] --> Router[Optional patched OE router]
    Router --> Backend
    Remote --> Helper[OE navigation helper]
    Helper --> Direct[/klipperai/direct]
    Direct --> Router
```

nginx and the OE router strip the public prefix before forwarding. The service
passes its configured prefix to Uvicorn for correct mounted-asset routing.
The HTML and transport keep API requests under that prefix, including sessions,
SSE, history, deletion and proposal rechecks. Match the prefix and port across
KlipperAI settings, nginx, Mainsail navigation and OE patch options.

nginx redirects the bare prefix while preserving query strings, disables response
buffering, and permits long SSE reads. The OE router handles the bare prefix with
or without a query and preserves the remainder of the URL. A blocked popup falls
back to same-tab navigation. Failed popup URL replacement or invalid fetched HTML
falls back to a real page load.

## Installer ownership

`sh install.sh` re-executes in Bash and sources the ordered manifest
`deployment/installer/modules.txt`. Sourcing a module performs no installation.
The entry point calls these phases:

1. `preflight.sh`: Linux and required-command checks.
2. `configure-paths.sh`, `configure-options.sh`: account, paths and interactive choices.
3. `install-python-package.sh`: Python selection, virtual environment and package install.
4. `install-service-configuration.sh`: application settings, profile, Moonraker integration, systemd and nginx.
5. `install-access-integrations.sh`: chosen Mainsail and OE integration helpers.
6. `print-next-steps.sh`: installed paths and manual follow-up.

Supporting functions live in `common.sh`, `python.sh`, `accounts.sh`,
`discovery.sh`, `settings.sh`, `moonraker.sh`, `service.sh`, `nginx.sh`,
`integrations.sh`, and `summary.sh`. nginx validation failure stops reload and
lets the phase restore its previous server-block backup.

Installation writes application/service/proxy configuration and selected access
integrations. It does not offer printer macros, shell-command extensions or edits
to `printer.cfg`. The application remains read-only toward printer files.
The separate historical macro installer is retained outside the guided flow.

The supported Mainsail sidebar integration uses `.theme/navi.json`.
`integrations/mainsail/navigation.py` owns pure entry merging, `navigation_file.py`
owns snapshots/backups/atomic replacement, `nav_cli.py` owns manual and automatic
modes, and `nav_hook.py` installs the systemd watcher and timer. Automatic repair
checks at boot and every five minutes, as well as on file changes. Explicit
navigation removal pauses repair; full uninstall removes the units first.
Saved settings live beside the printer config directory, so boot checks do not
depend on an interactive shell environment. See the
[Mainsail maintenance guide](../integrations/mainsail/README.md).

The optional OE integration separates reversible text transformation
(`route_patch.py` and templates), deployment/backups (`patch_files.py`), recovery
state and process locking (`maintenance_state.py`), and update coordination
(`update_coordinator.py`). `maintenance.py` provides the administrative CLI;
shell entry points select the interpreter and install the systemd watcher/timer.
Missing or duplicate upstream anchors stop patching before either target changes.
Busy, missing or invalid Moonraker update state leaves the checkout and suspension
marker unchanged. Failed restarts and refreshes are retried without rewriting
current files. The generated runner retains its custom storage directory even
without `HOME` or environment overrides. See the
[OE maintenance guide](../integrations/octoeverywhere/README.md) for recovery state,
upgrade instructions and limits of coordination with external updaters.

## Verification

```sh
python -m pytest
node --test tests/*.test.mjs
sh install.sh --check
ruff check klipperai_agent tests tools integrations
ruff format --check klipperai_agent tests tools integrations
mypy klipperai_agent --ignore-missing-imports
mypy integrations --ignore-missing-imports
python tools/project_map.py --check
uv build
```

Python tests include temporary Mainsail/OE checkouts, fake service commands, a local
Moonraker update fixture, interrupted writes, process-lock contention, restart and
refresh retries, and HTTP tests at default/custom prefixes. The 100% statement
coverage gate includes the standalone Mainsail/OE helpers and shared process lock. JavaScript
tests load the script manifest and exercise transport, application composition,
DOM output and OE popup/rescue paths. These are offline checks, not a rendered
browser check or a live printer, nginx, OE tunnel or model-provider test.

For release validation, install the wheel outside the checkout and verify its
entry points, inline bundle, mounted assets and persistent investigations. The
source archive must also include the installer manifest, modules and integrations.
On a real Linux host, verify both local Mainsail and the OE portal, including a
streamed question, reload/restored history, manual proposal recheck and deletion.
