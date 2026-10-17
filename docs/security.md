# Security and local deployment

KlipperAI is a shared printer assistant. It has no user accounts or built-in
authentication. Anyone who can reach its HTTP API can create a UI session, read
printer evidence and saved conversations, change the assistant's knowledge, and
trigger provider requests charged to the configured key. A session ID is an
expiring conversation handle, **not an authentication credential**. Session IDs
do not isolate different people using the same printer.

## Deployment boundary

The installed daemon binds to `127.0.0.1:8811`. nginx exposes `/klipperai/` on the
printer's existing web origin. Protect that route with the same authenticated
access boundary as the rest of the printer. Moonraker authentication does not
automatically protect this separate application. Do not forward port 8811 or
publish the nginx route directly to the Internet. For remote access, use an
authenticated tunnel or proxy and HTTPS; verify its authentication covers the
UI, every `/api/` route, streaming requests and cached-document downloads.

The shipped nginx snippet does not install accounts, TLS certificates or an
authentication gateway. An OctoEverywhere integration relies on OctoEverywhere's
access controls and correct routing. A trusted LAN deployment assumes everyone
who can reach the printer is allowed to use the assistant. Host root, the service
account, and processes running as that same account remain trusted.

The optional Moonraker agent connection uses the local Unix socket and therefore
relies on host socket permissions. Its extension methods inherit Moonraker's
client-access boundary. They expose capabilities, bounded public printer status
and ephemeral UI sessions, with no chat execution or printer commands. The only
Moonraker database write replaces the fixed `klipperai` namespace's `integration`
item with public capability/version metadata. Credentials, session IDs, prompts
and investigation history are never written there or broadcast as agent events.
See [Moonraker integration](moonraker-integration.md) for configuration and limits.

Browser protections complement that boundary:

- API requests marked `Sec-Fetch-Site: cross-site` are rejected. Other requests
  with an Origin must match the request origin or an explicit trusted origin.
  `same-origin` Fetch Metadata accommodates trusted proxies that rewrite Host.
- API bodies with an explicit media type must use JSON, so browser form posts
  cannot silently invoke API operations.
- Responses disable caching and referrer forwarding, disallow content sniffing,
  and restrict framing to the same origin. The CSP also disables object embeds
  and base-URL changes; it is not a complete script policy because the packaged
  UI uses inline scripts and styles.
- Interactive API documentation routes are disabled.

HTTP clients can forge Origin and Fetch Metadata. These checks are not a login
system and do not prevent direct access by another LAN user. Fetch Metadata's
purpose and limitations are described in the
[OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).

## Host and proxy configuration

Optional `[security]` settings in `klipperai.cfg` (or corresponding
`KLIPPERAI_` environment variables):

```ini
security_allowed_hosts: printer.local, 192.168.1.25
security_allowed_origins:
```

Allowed hosts are comma-separated hostnames/IPs without schemes, paths or ports;
include every name used by your local or remote proxy. The default is `*` for
existing printer/proxy compatibility. **The wildcard default does not defend
against DNS rebinding.** An explicit list uses
[Starlette TrustedHostMiddleware](https://starlette.dev/middleware/#trustedhostmiddleware)
to reject other Host headers. Test both local and remote access after changing it.

Leave allowed origins empty normally. If a trusted proxy rewrites Host and a
client supplies Origin without same-origin Fetch Metadata, list the original
origin including its scheme and nonstandard port, for example
`https://printer.example:8443`. This does not enable CORS or allow requests
explicitly marked cross-site. Do not list unrelated websites.

nginx preserves the incoming Host including its port, clears Forwarded and
X-Forwarded-Host, supplies forwarding metadata, and retains unbuffered SSE
responses. Uvicorn trusts forwarding headers only from loopback proxies.
Request-size policy remains the existing nginx/server configuration; this
milestone adds no request-size, concurrency or artifact-count limits.

The service retains `NoNewPrivileges=yes` and `PrivateTmp=yes`, adds `UMask=0077`,
and disables Python bytecode writes. It continues to use the selected printer
service account and existing host access. It does not install a new filesystem
sandbox or narrow the available diagnostic sources. Prefer an unprivileged
printer account where the host supports one; a vendor installation running as
root retains root access. Do not assume the systemd unit isolates a compromised
service from the printer account. See the upstream
[systemd execution settings](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html).

## Secrets and application storage

Provider settings can now save and rotate keys in private service-user storage
outside the checkout. See [provider management](providers.md) for permissions,
precedence, usage controls and manual restart behavior. Storage uses OS access
controls, not encryption at rest. Anyone admitted by the existing trusted
deployment boundary can change these shared settings; UI sessions are not admin
authentication.

Before the first UI save, keep the provider key in `/etc/klipperai/klipperai.env` as
`KLIPPERAI_OPENAI_API_KEY`. The installer writes this file with mode `0600` and
tightens an existing file before making its backup. `klipperai.cfg`, which is
normally editable through Mainsail, rejects `openai_api_key`; move any existing
entry to the environment file and remove it from the config before restarting.
The system service reads the environment file; it does not send the key to the UI.

For local development, `.env` is ignored by Git but still requires appropriate
local file permissions. On Linux use owner-only access; on Windows restrict its
ACL to your user and administrators. POSIX modes do not enforce Windows ACLs.
Do not include either environment file in printer-config exports or support bundles.

The installer creates the application data directory with mode `0700`. New
SQLite databases and runtime log files are opened with mode `0600` before writing
content, including newly rotated active logs. File writers reject symlinks,
hardlinks and special files. These checks do not defend against a malicious
process with the same UID replacing parent directories; that account is trusted.
Existing databases have their file permissions tightened when opened. Existing
parent-directory permissions are not silently rewritten by the Python runtime;
review them when upgrading an installation without rerunning the installer.

The agent's own runtime log now lives at `<data_dir>/logs/klipperai.log`
(normally `/var/lib/klipperai/logs/klipperai.log`). It is private application data
and is no longer automatically published through Mainsail's printer-log directory.
`agent_log_file_name` accepts a plain `.log` filename. The configured printer-log
directory, all-current-log collection, external config includes and existing
diagnostic settings retain their previous behavior.

Uvicorn access logging and the supplied nginx location's access logging are off
to avoid recording session IDs in query strings. Application log messages omit
session IDs. Parent proxy logs, nginx error logs, browser history and old logs
may still retain URLs; review those separately. Ordinary application logs retain
tool names, error tracebacks and diagnostic summaries with credential redaction.

## Redaction and retained data

Best-effort redaction recognizes common password, API-key, token, cookie,
authorization and session assignments; Basic/Bearer tokens; URL passwords;
OpenAI-style keys; indented secret values; and PEM private-key blocks. Text
redaction uses `[REDACTED]` (or stars for short values) without expanding text,
and preserves newline counts so evidence line references stay meaningful.
Config digests still use the original unredacted content to detect stale manual proposals.
Collection never rewrites the printer's config or log files.

Redaction is applied before collected config/log excerpts are clipped, at agent
tool/model-input and public-result boundaries, on chat/history/artifact input,
and on saved investigation outcomes. Old investigation rows and old knowledge
facts are redacted when read. Runtime log formatting also removes the exact
configured provider key, including in tracebacks. Diagnostic subprocesses do
not inherit `KLIPPERAI_OPENAI_API_KEY` or `OPENAI_API_KEY`. The legacy single-pass
provider also removes its exact key from prompt text while retaining it in the
HTTP authorization header.

Public web search refuses queries with recognizable credentials. Documentation
URLs containing recognizable credentials are rejected, including redirect
targets. Existing public-HTTPS and destination-address checks remain in place.
Component models, revisions and public documentation queries still leave the
host when knowledge research or hosted web search is enabled. Chat and Debug
send their documented printer context to the configured model provider; see
[agent modes](agent-modes.md) and [printer knowledge](printer-knowledge.md).

Redaction is not exhaustive: opaque unlabeled secrets, unusual encodings,
personal data and identifying device details may remain. Review pasted material
and collected evidence before sharing it. Cached originals are public manuals,
not sanitized private uploads. Existing raw database pages, exports, backups,
old shared logs and browser drafts are not retroactively scrubbed. If a key was
previously exposed, replace it and handle retained copies through your normal
backup and deletion procedures. Do not treat redaction as permission to publish
the entire application data directory.

## Model and printer boundary

Logs, configs, manuals, search results and model output are evidence rather than
trusted instructions. Tools keep the existing validated, read-only contracts;
the model cannot select arbitrary shell commands or perform printer motion,
heating, restarts or config writes. Config proposals require manual review and
manual editing. Knowledge edits and conversation deletion affect application
storage only. Host-tool minimization and new request/artifact limits were
explicitly removed from Milestone 9 at the user's request.

## Verification

Security regressions cover credential patterns, evidence and history boundaries,
file creation/rotation, browser origins, host allowlists, session preservation,
streaming, compatibility workflows and deployment rendering. Tests use local
fixtures and mocked providers. POSIX permissions and systemd/nginx enforcement
still need verification on the actual Linux printer; Windows tests cannot prove
those host controls. Remote proxy authentication and real provider/printer
behavior require their own live checks.
