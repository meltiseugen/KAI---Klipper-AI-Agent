# Mainsail Integration Assets

This directory contains both the recommended low-coupling Mainsail integration assets and an optional native-shell patch bundle.

## Recommended `v1` Integration

The default `v1` path is a supported custom navigation entry in Mainsail:

- it points to `/klipperai/`
- it opens KlipperAI in a new browser tab by default
- it does not require forking or patching Mainsail
- it survives upstream Mainsail web updates much better than direct file modifications

Use:

```bash
chmod +x ./integrations/mainsail/install-custom-nav.sh
./integrations/mainsail/install-custom-nav.sh --config-dir /home/pi/printer_data/config
```

This writes or updates:

- `/home/pi/printer_data/config/.theme/navi.json`

The example payload lives in `integrations/mainsail/navi.json.example`. This is
the **KlipperAI button in Mainsail's left navigation menu**, using Mainsail's
[documented customization format](https://github.com/mainsail-crew/docs/blob/zensical/docs/features/custom-themes/custom-navigation.md).
The optional top-bar/drawer patch below is a separate integration.

The helper validates JSON, preserves unrelated entries and their order, removes
duplicate matching KlipperAI entries, and replaces the navigation file atomically.
An already correct entry preserves the file's bytes and timestamp. A missing
`.theme` directory or `navi.json` can be recreated; a missing printer config
directory or malformed existing JSON is an error, with no overwrite. Symlinked
theme directories and linked navigation files are refused.

## Automatic Repair And Startup Checks

The guided installer offers automatic repair when installing the sidebar link,
enabled by default. For an existing installation:

```bash
sh integrations/mainsail/install-auto-reapply.sh \
  --config-dir /home/pi/printer_data/config \
  --href /klipperai/ --target _blank
```

This installs `klipperai-mainsail-reapply.service`, `.path` and `.timer` under
`/etc/systemd/system`. The service runs as the config directory's owner by
default (`--user` overrides it). The wrapper requests sudo only to install or
remove systemd units. Ordinary manual navigation edits run as the calling user;
run them as the config owner.

Checks run:

- once during installation;
- at system startup, scheduled about 30 seconds after boot;
- when the navigation file or theme directory changes;
- every five minutes after the last check completes, including failed checks.

The OctoEverywhere hook also schedules its startup check after 30 seconds, once
its service/network dependencies are ready. Rerun its hook installer after
upgrading KlipperAI to refresh existing unit definitions.

Mainsail navigation repair needs no network access, rebuild, Moonraker update
coordination, nginx reload or printer service restart. The customization lives
outside Mainsail's web release files; automatic repair also covers deleted or
replaced theme files during restores. Refresh an already open Mainsail page to
load a repaired navigation entry. Hidden entries in Mainsail's interface settings
and browser caches are separate from the on-disk navigation configuration.

Options from the manual helper (`--href`, `--title`, `--target`, `--position`,
`--icon`) are saved for future checks. `--interval 5min` changes the fallback
interval; positive `s`, `min`, and `h` values are accepted. Rerun the hook installer
with the complete desired options when changing them. A one-off manual edit
does not change the hook's saved settings.

State defaults to `<printer-data>/.klipperai-mainsail`, beside the config directory.
Use `--state-dir PATH` consistently for manual and automatic commands to override
it. The state directory contains saved settings, the shared process lock, a
removal flag and unique `backups/change-*/navi.json` originals. Backups are created
only when an existing navigation file needs changing; retain them for recovery
or remove old backups manually. Existing `.bak.*` files are left alone.

Concurrent KlipperAI operations share an OS-owned lock, released even if a
process exits abnormally. File snapshots are rechecked just before replacement
to avoid overwriting concurrent edits. External editors do not share our lock,
so this reduces races without promising a transaction with another process.

### Inspect And Remove

```bash
# Read-only content check: 0 = current, 1 = repair needed or an error.
sh integrations/mainsail/install-custom-nav.sh \
  --config-dir /home/pi/printer_data/config --check

systemctl status klipperai-mainsail-reapply.timer klipperai-mainsail-reapply.path
journalctl -u klipperai-mainsail-reapply.service -n 50 --no-pager

# Stop/remove automation while keeping the link and recovery backups.
sh integrations/mainsail/uninstall-auto-reapply.sh

# Remove the link; also pauses automatic repair if its units are still enabled.
sh integrations/mainsail/uninstall-custom-nav.sh \
  --config-dir /home/pi/printer_data/config
```

Repeat custom identity/state options when checking or removing a customized
entry. The helper identifies its entries by matching the configured title or
URL, as before. An explicit manual installation or hook installation resumes
repair after removal. Full KlipperAI uninstall stops and removes these units
before deleting the navigation entry or checkout.

## Maintenance Ownership

| File | Responsibility |
| --- | --- |
| `navigation.py` | Validated entry options and pure JSON transformations |
| `navigation_file.py` | Snapshots, backups, ownership and atomic replacement |
| `nav_cli.py` | Manual/check/remove/reconcile entry points and removal flag |
| `nav_hook.py` | Saved options and systemd installation/removal |
| `../host_lock.py` | Process locking shared with the OE maintenance helper |
| `*-custom-nav.sh`, `*-auto-reapply.sh`, `run-nav.sh` | Stable shell entry points and interpreter selection |

These administrative helpers are outside the agent's read-only tool/API surface.
Python 3.10+ and the standard library are sufficient. Regression tests cover
navigation loss, malformed JSON, concurrent edits, interrupted writes, saved
options, startup units and uninstall behavior. They do not constitute a live
Linux boot or rendered Mainsail browser test.

## Optional Native Shell Patch

### Intent

The native patch keeps Mainsail changes deliberately small:

- add a KlipperAI launcher button to the top bar
- mount a native Mainsail shell component
- open a right-side drawer
- bootstrap a KlipperAI UI session from `/klipperai/api/ui-sessions`
- render the embedded assistant in an iframe

The actual assistant UI and workflow logic remain in the KlipperAI service.

## Target Upstream

- Repository: `https://github.com/mainsail-crew/mainsail`
- Branch inspected: `develop`
- Commit used for this patch bundle: `6130a0aa1776a138feaab691b9e4b1334b676b79`
- Upstream package version at that commit: `2.17.0`

## Files Touched In Upstream Mainsail

- `src/App.vue`
- `src/components/TheTopbar.vue`
- `src/components/integrations/KlipperAiShell.vue`

## What The Patch Adds

### App-Level Shell Mount

`App.vue` is patched to:

- listen for a `toggle-klipperai` event from the top bar
- keep a local `showKlipperAiShell` boolean
- mount the drawer shell component

### Topbar Launcher

`TheTopbar.vue` is patched to:

- add a `KlipperAI` icon button beside the existing topbar controls
- emit `toggle-klipperai` upward

### Embedded Drawer

`KlipperAiShell.vue` is a thin Mainsail-native shell that:

- opens as a right-side drawer
- requests a UI session from `/klipperai/api/ui-sessions`
- shows a loading or error state if bootstrap fails
- loads the returned `embed_path` into an iframe

## Apply The Optional Patch

From a local Mainsail source checkout:

```bash
chmod +x ./integrations/mainsail/apply-patch.sh
./integrations/mainsail/apply-patch.sh /path/to/mainsail
```

The helper script runs `git apply --check` first, then applies the patch.

## Build And Deploy

After applying the patch in a Mainsail source checkout:

```bash
npm install
npm run build
```

Then deploy the generated Mainsail build as you normally would for your environment.

## Requirements

This shell patch assumes:

- KlipperAI is reverse-proxied on the same origin at `/klipperai/`
- `POST /klipperai/api/ui-sessions` is reachable from the Mainsail frontend
- `embed_path` points to an embeddable iframe route

## Current Limitations

- The patch does not add localization keys; the launcher label is effectively icon-first and the shell title is hardcoded `KlipperAI`.
- The patch is version-targeted to the upstream commit above and may need refreshing for future Mainsail releases.
- The patch bundle does not rebuild or deploy Mainsail automatically.
- The patch assumes the current `/klipperai` mount path.
