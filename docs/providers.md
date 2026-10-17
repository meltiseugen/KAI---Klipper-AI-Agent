# Provider and credential management

Open **Provider settings** in KlipperAI. The supported providers remain OpenAI
and Offline (`stub`). Offline makes no model requests. The panel manages the
service's shared provider configuration; access uses the same trusted proxy/LAN
boundary as the rest of the application, not a separate administrator account.
Use HTTPS for remote access and protect every `/klipperai/api/` route.

## Setup and rotation

1. Select OpenAI, enter a new key, and set the model IDs and limits.
2. Choose **Validate and save**. KlipperAI checks access to each distinct model
   through OpenAI's model metadata endpoint before committing anything.
3. Manually restart the KlipperAI service. The panel distinguishes saved settings
   from the active provider and explicitly shows pending changes. No restart or
   printer-write endpoint is added.
4. Check a real request after restarting. When rotating, revoke the old key in
   the OpenAI account only after the replacement works. KlipperAI cannot revoke it.

**Check access** validates without saving. The key field clears after either
operation, on reload, and when closing the panel. Re-enter a replacement key after
a check or failed save. An empty field keeps the current credential. To remove it,
select Offline and check **Remove stored key**. Removal also takes effect after
manual restart and suppresses fallback to an old environment key.

Validation sends no printer context and generates no model response. It checks
authentication and model-read access, not credits, Responses/Chat Completions
permissions, tool support or reasoning-option compatibility. A restricted key
must allow model metadata reads. Provider errors never return raw response bodies
or credential values to the UI. Conflicting edits return 409; reload before saving.

## Private storage and configuration precedence

The default is `~/.config/klipperai/providers.sqlite3` under the **service user's**
home. `provider_storage_dir` / `KLIPPERAI_PROVIDER_STORAGE_DIR` can select a dedicated
private directory. The directory is mode 0700 and the file is mode 0600 on POSIX.
It must be outside the checkout, printer configuration, G-code and log directories.
Symlink directories/files, hardlinked files and special files are rejected.
The directory is dedicated to these settings; its permissions are tightened.

Credentials are protected by OS permissions, **not encrypted at rest**. Root and
the service account remain trusted. On Windows, restrict the directory's ACL to
the service user and administrators; POSIX modes do not enforce Windows ACLs.
Exclude this directory and its SQLite auxiliary files from support bundles and
public backups. SQLite secure deletion is enabled, but snapshots and filesystem
backups can still retain old keys. There are no credential-read/export endpoints.

Before the first save, existing `llm_provider`, `openai_model`,
`agent_max_output_tokens`, `web_search_enabled`, and the protected
`KLIPPERAI_OPENAI_API_KEY` environment value supply defaults. The first save stores
one complete provider policy and the effective key atomically. Subsequently that
saved policy takes precedence over those environment/config defaults, including
an explicitly removed key. Other runtime settings remain unchanged.
Saving does not rewrite or remove existing `.env` or installer environment files;
remove obsolete credentials from those files and their backups during rotation.

## Models and usage safety

Separate profiles route Chat/Debug agent calls, hosted web search, knowledge
extraction, and legacy compatibility calls. Each has a model ID, output-token
cap, and optional reasoning effort. `Model default` omits the reasoning option.
The existing model default is preserved; the UI does not infer capabilities or
prices from names. Choose options supported by your selected models. Hosted
search can be disabled globally. Output caps include reasoning tokens where the
provider's API does; a smaller call-specific limit is respected.

All production OpenAI clients share one guard and a persistent usage ledger:

- Defaults: 20 calls/minute, 200 calls/UTC day, 2,000,000 accounted tokens/day,
  and at most 2 simultaneous generation requests per service process.
- Every model step and hosted-search/research/legacy call consumes a request.
  Metadata validation also consumes request quota but no token reservation.
- Generation reserves UTF-8 request bytes plus framing allowance and maximum
  output tokens before sending. Reported total tokens replace that reservation.
  Failed, cancelled or missing-usage responses keep their reservation.
- SQLite transactions prevent concurrent requests from overspending the remaining
  local allowance. Counts survive restart, rotation, and policy changes. Daily
  usage resets at midnight UTC; per-minute usage uses a rolling window.
- HTTP 429 establishes a persisted cooldown. Numeric Retry-After is honored within
  1–3600 seconds; absent/invalid/date-form headers use 60 seconds. There are no
  automatic retries that silently generate additional spend.

This is a local safety budget, not an exact invoice or hard dollar cap. Hosted
search charges and provider-internal context cannot be bounded by local token
estimates. Configure spending restrictions at the provider too. Existing agent
step, deadline, context and tool-call limits continue to apply. If a run hits a
provider guard, it stops or reports incomplete evidence using existing error paths.

## Verification

Offline tests cover atomic persistence, stale editors, failed validation, secret
omission, restart/removal semantics, task routing, shared budgets, cancellation,
cooldowns and HTTP session/origin enforcement. Browser/DOM checks are separate
from live provider and printer checks. No fixture establishes real account model
access, billing behavior, Linux file enforcement or printer behavior.

Protocol references: [model access](https://developers.openai.com/api/reference/resources/models/methods/retrieve),
[Responses](https://developers.openai.com/api/reference/resources/responses/methods/create),
[provider rate limits](https://developers.openai.com/api/docs/guides/rate-limits).
