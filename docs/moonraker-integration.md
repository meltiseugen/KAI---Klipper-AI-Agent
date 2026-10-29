# Moonraker integration

KlipperAI registers as the `klipperai` agent over Moonraker's local Unix socket.
The daemon identifies on every connection, publishes fixed capability metadata,
subscribes to available printer objects and reconnects after connection loss.
This uses Moonraker's documented [extension API](https://moonraker.readthedocs.io/en/latest/external_api/extensions/)
and [Unix-socket transport](https://moonraker.readthedocs.io/en/latest/external_api/introduction/#unix-socket-connection).
No Moonraker plugin or Klipper macro is required.

## Host setup

Defaults suit the standalone Linux daemon on the printer host. Optional settings
in `klipperai.cfg` are:

```ini
[moonraker]
moonraker_agent_enabled: true
moonraker_socket_path:
```

An empty path uses `<printer_data_root>/comms/moonraker.sock`. An explicit path
supports installations with a different Moonraker data directory. The environment
equivalents are `KLIPPERAI_MOONRAKER_AGENT_ENABLED` and
`KLIPPERAI_MOONRAKER_SOCKET_PATH`. Restart KlipperAI manually after changes.

The service account needs access to that socket. The local socket trusts OS
permissions and does not require a Moonraker API key. Leave its permissions under
the printer host's existing account boundary. Only one agent named `klipperai`
can register with a Moonraker instance at a time; stop duplicate daemons if
registration keeps failing. The UI reports reconnecting while a socket is absent,
inaccessible or unsupported; chat HTTP reads remain available independently.

If `moonraker_url` points to a non-loopback host, agent registration is disabled
unless a socket path is explicitly provided. That avoids implicitly subscribing
to a different local printer. Ensure both configured transports identify the
same printer. Remote WebSocket authentication is not implemented in this milestone.
Windows development can set `moonraker_agent_enabled: false`.

## State and recovery

The subscription includes only available objects from this fixed set:

| Object | Fields |
| --- | --- |
| `webhooks` | `state`, `state_message` |
| `print_stats` | `state`, `filename`, `message`, `print_duration`, `filament_used` |
| `virtual_sdcard` | `progress`, `is_active` |
| `extruder`, `heater_bed` | `temperature`, `target` |

Partial notifications merge into the snapshot; older timestamps are ignored.
Klipper shutdown/disconnect marks the snapshot stale. Ready events trigger a
fresh subscription with a new snapshot, including when Klipper's monotonic clock
has reset. Updates received during subscription setup are buffered and merged.
Only 32 such updates are retained; overflow forces a fresh connection.

Socket frames are limited to 128 KiB. Public strings are redacted and capped at
512 characters, numeric fields must be finite, and nested values are discarded.
Only the latest snapshot lives in memory, along with its UTC observation time and
Moonraker event time. Disconnect preserves that observation explicitly as stale.
This is not an event-history or incident-flight-recorder service.

The connection checks `server.info` every 30 seconds and bounds RPC calls to
10 seconds. Transport failures reconnect with delays growing from 1 to 30 seconds.
Socket EOF and Klipper lifecycle notifications are handled as they arrive; a
silent connection failure is detected by the next heartbeat and timeout.
Missing objects or failed subscriptions are retried on the next check.

The UI receives session-protected `GET /api/moonraker/events` SSE updates. It shows
`Events: live`, `Events: waiting for Klipper`, or `Events: reconnecting`, and
clears the current job indication when data becomes stale. Snapshots are coalesced
to at most one per second. Expired sessions close the stream and the UI obtains
a fresh session. `GET /api/moonraker?session_id=...` returns the same snapshot.
Both routes respect the configured public path prefix. SSE is independent from
chat streaming and does not make provider calls.

## Extension contract, version 1

Clients admitted by Moonraker can call these through `server.extensions.request`.
All three accept absent/null arguments or an empty object; any other arguments
are rejected. Unknown methods return JSON-RPC `-32601`, bad arguments `-32602`.

| Method | Result |
| --- | --- |
| `klipperai.capabilities` | Schema/version, supported methods/events, `printer_access: read_only`, notification version |
| `klipperai.status` | Connection/registration/subscription flags, Klipper state, public status, observation time, stale flag and sanitized error |
| `klipperai.create_ui_session` | `session_id`, relative `embed_path` with configured prefix, UTC `expires_at` |

For example, send this JSON-RPC request to Moonraker:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "server.extensions.request",
  "params": {
    "agent": "klipperai",
    "method": "klipperai.create_ui_session",
    "arguments": {}
  }
}
```

The session uses the same ephemeral store and expiry as the HTTP UI. Bootstrap is
limited to 10 sessions per rolling minute per daemon, returning `-32000` above
that limit. Session IDs are returned only to the requesting client and never
stored in Moonraker's database or included in broadcasts. As with HTTP sessions,
they are not account authentication; see [deployment security](security.md).

After identification, `connection.send_event` broadcasts `klipperai_ready` with
the capability document via Moonraker's `notify_agent_event`. This announces
extension availability, not printer readiness. The notification version and
supported-event list define a discovery contract for future public notifications.
There are no model-controlled notification sends, remote macro callbacks or
printer-control methods.

## Public database item

`server.database.post_item` writes namespace `klipperai`, key `integration`:

```json
{
  "schema_version": 1,
  "agent": "klipperai",
  "version": "0.1.0",
  "methods": ["klipperai.capabilities", "klipperai.status", "klipperai.create_ui_session"],
  "events": ["klipperai_ready"],
  "printer_access": "read_only",
  "notifications_version": 1
}
```

This item is replaced idempotently on registration and leaves other namespace
keys intact. It contains no credentials, sessions, prompts or conversation data.
It can remain after KlipperAI stops: use `server.extensions.list` to discover
connected agents and `klipperai.status` for live state. Database permission errors
set `metadata_registered: false`; observation continues and metadata is retried
on the next connection.

## File metadata evidence

The model tool `get_gcode_metadata` accepts an optional relative G-code filename.
Without one it reads the current `print_stats.filename`. It queries Moonraker's
parsed metadata endpoint, then returns only size/time, slicer, layer, filament,
nozzle and first-layer temperature fields. Raw G-code, thumbnails and filesystem
paths from the response are excluded. Absolute paths, traversal and control
characters are rejected; the filename is query-encoded.

The result includes an observation time and a source citation under `gcodes/`.
These are slicer/file estimates, not proof of active printer settings or actual
completed-job measurements. Missing current files, unavailable metadata and HTTP
failures produce recoverable tool errors. The tool cannot open arbitrary files,
start a print or modify metadata.

## Verification

Automated tests exercise ETX framing, registration, public-only database writes,
method dispatch, session expiry/rate limits, partial notifications, restart races,
reconnects, shutdown cleanup, metadata filtering and subsequent model observations.
HTTP and DOM tests cover session-protected snapshots/SSE, live/stale badges,
session renewal and page lifecycle. These fixtures do not prove behavior on a
physical printer or through an actual browser/proxy.

On a host, check `server.extensions.list` for `klipperai`, open the UI to verify
the event badge and inspect the public database item. Confirm updates during
normal printer activity and recovery following an independently planned service
restart. Live provider and printer checks must be recorded separately from the
automated suite; none is performed automatically by these tests.
