# OctoEverywhere Host Patch

This integration is an unsupported local patch for an existing Klipper
OctoEverywhere checkout. It is intended for hosts where:

- the main OctoEverywhere printer portal still serves Mainsail or Fluidd
- `Shared Connection` URLs are not desired for KlipperAI
- KlipperAI is already installed locally and reachable behind nginx at `/klipperai/`

What the patch does:

- extends OctoEverywhere's Moonraker-side relative-path router so requests for
  `/klipperai` and `/klipperai/...` are forwarded directly to the local KlipperAI
  backend on `127.0.0.1:8811`
- patches OctoEverywhere's injected frontend helper so the `KlipperAI` nav item
  bypasses the Mainsail SPA/router and can open KlipperAI in either the current
  tab or a new tab

What it does not do:

- it does not patch Mainsail itself
- it does not add a second officially supported frontend to OctoEverywhere
- it does not keep the OctoEverywhere checkout clean while the route is active;
  the optional update hook temporarily removes only KlipperAI's marked blocks
  when Moonraker reports a pending OE update

## Assumptions

- OctoEverywhere checkout path: `/home/<service-user>/octoeverywhere`
  or, on rooted Creality Nebula Pad-style layouts, `/usr/data/octoeverywhere`
- KlipperAI backend port: `8811`
- KlipperAI public prefix: `/klipperai`

If your host differs, pass explicit arguments to the helper script.

If `install.sh` detects an OctoEverywhere checkout, it can offer to run this
helper automatically.

## Apply

From the KlipperAI checkout on the host:

```bash
chmod +x integrations/octoeverywhere/apply-local-klipperai-route-patch.sh
./integrations/octoeverywhere/apply-local-klipperai-route-patch.sh \
  --oe-root /home/<service-user>/octoeverywhere \
  --restart-service
```

Rooted Creality Nebula Pad example:

```bash
./integrations/octoeverywhere/apply-local-klipperai-route-patch.sh \
  --oe-root /usr/data/octoeverywhere \
  --restart-service
```

Optional flags:

- `--klipperai-prefix /klipperai`
- `--klipperai-port 8811`
- `--nav-target _blank`
- `--service octoeverywhere`
- `--state-dir /etc/klipperai`

Before changing either target, the helper validates both outputs and saves both
original files in a unique `change-*` directory under
`/etc/klipperai/octoeverywhere-backups`. Each replacement is atomic and preserves
the original mode and owner. Unchanged files keep their contents and timestamps;
an already current patch creates no backup and requires no restart.

## Automatic Update Coordination

Install the systemd path/timer hook to coordinate Moonraker-managed OE updates:

```bash
sh integrations/octoeverywhere/install-auto-reapply.sh \
  --oe-root /home/biqu/octoeverywhere \
  --klipperai-prefix /klipperai \
  --klipperai-port 8811 \
  --nav-target _blank \
  --service octoeverywhere
```

The hook:

- checks Moonraker's `octoeverywhere` update-manager state
- leaves the checkout and suspension marker untouched while an update is busy,
  or when the request fails or required update fields are missing/invalid
- removes only KlipperAI's marked blocks when OE has pending commits
- leaves unrelated local changes in the two OE files intact
- refreshes Moonraker so the checkout can become updateable
- compares both files with the configured patch contents, repairing missing,
  partial or outdated patches after the OE update
- watches the patched files and KlipperAI templates for changes
- runs a five-minute fallback timer after a check completes, including failures
- schedules a check at every system startup, about 30 seconds after boot once
  service/network dependencies are ready
- retries failed service restarts and Moonraker refreshes using persistent markers
- enables future retries even if the initial Moonraker query fails
- moves legacy `*.klippyai-backup-*` files out of the OE checkout and into
  `/etc/klipperai/octoeverywhere-backups/legacy`

The runner retains a custom `KLIPPERAI_STATE_DIR` supplied during installation,
including under systemd where `HOME` and interactive environment variables may
be absent. Status validation follows Moonraker's
[update-manager API](https://moonraker.readthedocs.io/en/latest/external_api/update_manager/).

Keep the path watcher plus timer: file events give prompt repair, and the timer
covers missed events, startup ordering and transient failures. A supported
upstream route-extension API would remove the need for source patching; this
integration does not currently use one. A separate cron job or repeated blind
patch application would not resolve update coordination or partial failures.

Manual patching and automatic checks share an OS-owned process lock in the state
directory. Use the same `--state-dir` for both. Process exit releases the lock,
including abnormal exit; the lock file itself deliberately remains. Moonraker
does not share this lock. The helper checks update status twice before changes,
checks Git operation markers and verifies file snapshots before replacement.
These checks reduce races with external updaters, but the pair of files is not a
single filesystem transaction. Caught write failures roll back our own writes;
an interrupted process can leave a partial patch for the next check to repair.

Recovery state under the configured directory:

| File | Meaning |
| --- | --- |
| `octoeverywhere-reapply.suspended` | Patch removed while waiting for an OE update; cleared after successful reapplication |
| `octoeverywhere-restart-pending` | Files changed; retry restart until it succeeds |
| `octoeverywhere-refresh-pending` | Patch removed; retry Moonraker update refresh until it succeeds |
| `octoeverywhere-maintenance.lock` | Shared process lock, not an indication that a process is still running |

After upgrading KlipperAI, rerun the hook installation command with your existing
paths, prefix, port and service options to refresh the systemd units. Existing
generated runners remain compatible and keep their saved settings. No separate
maintenance daemon or additional Python dependency is required; the helper uses
KlipperAI's virtual environment when available.

Installed artifacts:

- `/usr/local/bin/klipperai-octoeverywhere-reapply`
- `/etc/systemd/system/klipperai-octoeverywhere-reapply.service`
- `/etc/systemd/system/klipperai-octoeverywhere-reapply.timer`
- `/etc/systemd/system/klipperai-octoeverywhere-reapply.path`

## Updating OctoEverywhere

With the automatic hook installed, refresh Moonraker updates and wait for the
hook to remove the patch before clicking `Update`. Manual preparation remains
available:

```bash
sh integrations/octoeverywhere/apply-local-klipperai-route-patch.sh \
  --oe-root /home/biqu/octoeverywhere \
  --restore-original \
  --restart-service \
  --service octoeverywhere
```

The restore operation removes the marked KlipperAI blocks rather than resetting
the whole files from git. After the OE update, the path/timer hook reapplies the
patch. Manual reapplication remains available:

```bash
sh integrations/octoeverywhere/apply-local-klipperai-route-patch.sh \
  --oe-root /home/biqu/octoeverywhere \
  --klipperai-prefix /klipperai \
  --klipperai-port 8811 \
  --nav-target _blank \
  --restart-service \
  --service octoeverywhere
```

Reapplying with a successful requested restart clears the suspend marker. If no
restart was requested, the helper records that one is still needed.

## Verify

Check the on-disk patch without changing OE files, service state or recovery
markers (exit code `0` means current, `1` means absent, outdated or an error):

```bash
sh integrations/octoeverywhere/apply-local-klipperai-route-patch.sh \
  --oe-root /home/biqu/octoeverywhere --check
```

Include your custom prefix, port and navigation target when checking a customized
installation. This checks file contents, not whether the service has loaded them.
Inspect automatic maintenance with:

```bash
systemctl status klipperai-octoeverywhere-reapply.timer klipperai-octoeverywhere-reapply.path
journalctl -u klipperai-octoeverywhere-reapply.service -n 50 --no-pager
```

After the script restarts OctoEverywhere:

1. hard-refresh the OctoEverywhere printer portal
2. open `https://<printer>.octoeverywhere.com/klipperai/`
3. click the `KlipperAI` navigation entry from the OE-hosted Mainsail sidebar

If the browser still serves cached Mainsail shell content on the first try,
repeat the test in an incognito window.

## Rollback

Run the patch helper with `--restore-original --restart-service`. The script
also saves the pre-restore files under `/etc/klipperai/octoeverywhere-backups`.

For a lasting rollback, first stop and disable the auto-reapply timer/path if
installed; otherwise they intentionally restore the patch once OE is current:

```bash
sudo systemctl disable --now klipperai-octoeverywhere-reapply.timer klipperai-octoeverywhere-reapply.path
sudo systemctl stop klipperai-octoeverywhere-reapply.service
```

## Maintenance

The patch and exact restore were checked against the current upstream
[router](https://github.com/QuinnDamerell/OctoPrint-OctoEverywhere/blob/master/moonraker_octoeverywhere/moonrakerapirouter.py)
and [UI helper](https://github.com/QuinnDamerell/OctoPrint-OctoEverywhere/blob/master/moonraker_octoeverywhere/static/oe-ui.js)
on 2026-10-13. This source compatibility check does not prove live tunnel behavior.
The automatic
hook logs a failed reapplication instead of resetting upstream files if these
anchors change:

- `moonraker_octoeverywhere/moonrakerapirouter.py`
- `moonraker_octoeverywhere/static/oe-ui.js`

The patch engine and templates are separate from deployment and update
coordination:

| File | Responsibility |
| --- | --- |
| `route_patch.py`, `router.template`, `navigation.js` | Reversible text transformations and anchor validation |
| `patch_files.py` | File inspection, backups, staging, replacement and rollback |
| `maintenance_state.py`, `../host_lock.py` | Persistent recovery markers and shared process-lock implementation |
| `update_coordinator.py` | Moonraker state, update preparation and restart/refresh retries |
| `maintenance.py` | Administrative CLI and option validation |
| `run-maintenance.sh`, `reapply.sh` | Interpreter selection, elevation and compatibility with saved runner settings |
| `install-auto-reapply.sh` | Install the systemd runner, watcher and timer |

These administrative helpers are not exposed as model tools or application API
endpoints. Routes include `/klipperai?query`, `/direct`, assets, streaming chat,
investigation history and manual proposal rechecks. Custom prefixes use the same
mapping. The rescued page stays self-contained; blocked popups fall back to a
normal navigation. See [frontend and installer ownership](../../docs/frontend-and-installation.md)
for the offline regression checks and remaining live verification steps.
