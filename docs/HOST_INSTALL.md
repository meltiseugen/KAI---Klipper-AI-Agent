# KlipperAI Host Install Guide

This guide is the shortest path to getting KlipperAI running on a Klipper or Kalico host that already has Moonraker and Mainsail installed.

After the initial install, use [the fast SSH update workflow](printer-testing.md)
to deploy development fixes and roll back code without regenerating settings.

Current runtime behavior:

- KlipperAI is `read-only`
- it can read logs, config files, and Moonraker state
- it can propose config snippets in chat
- it will **not** write printer/config files

## 1. Prerequisites

The host should already have Linux, Moonraker and Mainsail/Fluidd, root or sudo
access, network access, and enough writable storage for the checkout and packages.
It must use either real systemd 250+ with encrypted credential delivery or native
Creality init scripts.

Standard systemd installs use an unprivileged service account. Native rooted
Creality/Ender-3 V3 KE installs use their own init backend and root service account,
with authenticated host-key encryption and RAM-only master delivery. See
[native Creality installation](creality-compatibility.md) for setup, updates and
firmware acceptance checks. The installer distinguishes real systemd from a
compatibility `systemctl` command.

Run `sh install.sh`; it installs missing Bash before starting the Bash phases.
It then installs supported Python, required standard-library modules, pip,
venv/virtualenv, Git HTTPS support, certificates, utilities and missing nginx.
It preserves existing vendor nginx and prefers a supported `/opt` Python over an
old vendor interpreter. On old apt-based hosts it invokes the Python helper
automatically with one build job, beside the system Python.

The installer detects Entware outside PATH. On supported native Creality images
without a package manager, it can bootstrap Entware with checksum-pinned assets
while preserving existing `/opt` content. See [automatic prerequisite details](installer-prerequisites.md)
for supported feeds and bootstrap requirements. A broken existing package manager
or incompatible package feed is reported for repair rather than replaced.

On rooted Creality Nebula Pad-style layouts, the printer data root is usually:

- printer data root: `/usr/data/printer_data`
- Mainsail config dir: `/usr/data/printer_data/config`
- related host data: `/usr/data/mainsail`, `/usr/data/moonraker`, `/usr/data/nginx`
- OctoEverywhere checkout, when installed: `/usr/data/octoeverywhere`

The installer detects `/usr/data/printer_data` automatically when it exists. If
you are prompted for the printer data root on one of these pads, use
`/usr/data/printer_data`.

The native backend does not require systemd or sudo. It is selected automatically
for the vendor layout; `KLIPPERAI_SERVICE_MANAGER=appliance sh install.sh` selects it
explicitly. Standard systemd installs retain their existing encrypted credential path.

The default dependency set avoids Rust builds and disables optional Python
speedups. Native MIPS setup adds C build tools and Python headers when needed for
the encryption dependency. An OpenAI API key is required for agent responses;
the page provides provider setup until one is configured.

## 2. Clone The Repo

Run on the printer host:

If Git is not yet available, copy or extract the checkout onto the printer through
SSH first. Once the files are present, the installer installs Git automatically.
Keep native Creality checkouts on persistent storage, such as `/usr/data/KlipperAI`.

```bash
cd /home/<service-user>
git clone https://github.com/meltiseugen/KlipperAI.git
cd KlipperAI
```

Example for a common `biqu` host:

```bash
cd /home/biqu
git clone https://github.com/meltiseugen/KlipperAI.git
cd KlipperAI
```

## 3. Run The Installer

```sh
sh install.sh
```

If a previous install attempt created `.venv` with Python `3.9` or older, the updated installer will detect that and offer to recreate it.

The installer will ask for:

- Linux service user
- project checkout path
- printer data root
- Mainsail config directory
- Moonraker URL
- reverse-proxy root path
- local bind port
- local data directory
- LLM provider
- model name
- OpenAI API key if provider is `openai`
- whether to install the Mainsail navigation link

Recommended/default values:

- service user: your actual printer user, for example `biqu` or `pi`; native Creality defaults to `root`
- checkout path: `/home/<service-user>/KlipperAI`
- printer data root: `/home/<service-user>/printer_data`
- Mainsail config dir: `/home/<service-user>/printer_data/config`
- Moonraker URL: `http://127.0.0.1:7125`
- root path: `/klipperai`
- port: `8811`
- provider: `openai`
- model: `gpt-5.4-mini`

## 4. What The Installer Creates

The installer will:

- create a Python virtual environment in the repo
- install the package into that venv
- write `/etc/klipperai/klipperai.env` for non-secret bootstrap/install metadata, and provision encrypted provider credentials through the selected backend
- write `printer_data/config/klipperai/klipperai.cfg`
- detect the printer profile once and save it into `klipperai.cfg`
- write `printer_data/config/klipperai/klipperai-moonraker.cfg`
- append an include like `[include klipperai/klipperai-moonraker.cfg]` to `moonraker.conf` if needed
- add `klipperai-agent` to `printer_data/moonraker.asvc`
- install and start `klipperai-agent.service` on systemd, or `/etc/init.d/S99klipperai` on native Creality
- generate `/etc/klipperai/nginx-location.conf`
- optionally patch the selected Mainsail nginx server block to include that snippet
- optionally add a Mainsail nav link in `.theme/navi.json`
- keep Klipper macros, shell-command extensions and printer configuration outside the installation flow
- if OctoEverywhere is installed, optionally apply the local OE `/klipperai/` route patch automatically
- write the KlipperAI runtime log to `<data_dir>/logs/klipperai.log`

## 5. Edit nginx

The installer can patch nginx automatically and reload it after a successful config test.

If you choose not to let the installer patch nginx, add this line inside the Mainsail nginx `server` block manually:

```nginx
include /etc/klipperai/nginx-location.conf;
```

Common file locations:

- `/usr/data/nginx/nginx.conf`
- `/etc/nginx/conf.d/mainsail.conf`
- `/etc/nginx/sites-enabled/mainsail`
- `/etc/nginx/sites-available/mainsail`

Some Creality nginx configs contain separate Fluidd and Mainsail `server`
blocks in one file. In that layout, make sure the include is inside the
Mainsail server block too, usually the one with `listen 80` and
`root /usr/data/mainsail`.

Then reload nginx:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

## 6. Restart Moonraker

Moonraker needs to reload its include file and allowed-services file:

```bash
sudo systemctl restart moonraker
```

## 7. Verify The Install

Check both services:

```bash
systemctl status klipperai-agent --no-pager
systemctl status moonraker --no-pager
```

Check KlipperAI health:

```bash
curl http://127.0.0.1:8811/healthz
```

Open the UI:

```text
http://<printer-host>/klipperai/
```

If you enabled the Mainsail nav link:

- reload the Mainsail page
- click `KlipperAI`

Optional OctoEverywhere path:

- if you want the main OctoEverywhere printer portal to serve
  `https://<printer>.octoeverywhere.com/klipperai/` without using a Shared
  Connection URL, see
  [integrations/octoeverywhere/README.md](integrations/octoeverywhere/README.md)
  and apply the local OE host patch from this repo
- if the installer detects an OctoEverywhere checkout, it can offer to apply
  that patch for you during install
- on rooted Creality Nebula Pad-style layouts, the OctoEverywhere checkout is
  often `/usr/data/octoeverywhere`; pass that as `--oe-root` if applying the
  patch manually
- if you choose the OctoEverywhere patch in the installer, it can also install
  a systemd path/timer hook that removes KlipperAI's marked blocks when
  Moonraker reports a pending OE update and reapplies them afterward
- while the route is active, Moonraker still reports the two OE files as dirty;
  refresh updates and let the hook prepare the checkout before clicking `Update`

Manual CB1 auto-update hook install:

```bash
sh integrations/octoeverywhere/install-auto-reapply.sh \
  --oe-root /home/biqu/octoeverywhere \
  --klipperai-prefix /klipperai \
  --klipperai-port 8811 \
  --nav-target _blank \
  --service octoeverywhere
```

Prepare for an OctoEverywhere update:

```bash
sh integrations/octoeverywhere/apply-local-klipperai-route-patch.sh \
  --oe-root /home/biqu/octoeverywhere \
  --restore-original \
  --restart-service \
  --service octoeverywhere
```

After the OctoEverywhere update finishes, reapply KlipperAI:

```bash
sh integrations/octoeverywhere/apply-local-klipperai-route-patch.sh \
  --oe-root /home/biqu/octoeverywhere \
  --klipperai-prefix /klipperai \
  --klipperai-port 8811 \
  --nav-target _blank \
  --restart-service \
  --service octoeverywhere
```

## 8. Important Files

Editable runtime config:

- `/home/<service-user>/printer_data/config/klipperai/klipperai.cfg`

Legacy Klipper update macro files (only from earlier or separate manual installs):

- `/home/<service-user>/printer_data/config/klipperai/klipperai-macros.cfg`
- `/usr/local/bin/klipperai-self-update`
- `/etc/sudoers.d/klipperai-self-update`

Server-side API key and hidden install metadata:

- `/etc/klipperai/klipperai.env`

Moonraker include:

- `/home/<service-user>/printer_data/config/klipperai/klipperai-moonraker.cfg`

Generated nginx snippet:

- `/etc/klipperai/nginx-location.conf`

KlipperAI runtime log:

- `/var/lib/klipperai/logs/klipperai.log`

## 9. Change The Model Later

Edit:

- `printer_data/config/klipperai/klipperai.cfg`

Change:

```ini
[llm]
llm_provider = openai
openai_model = gpt-5.4-mini
```

Then restart:

```bash
sudo systemctl restart klipperai-agent
```

## 10. Rerun Printer Profile Detection

If the detected profile is wrong or you want to refresh it:

```bash
/home/<service-user>/KlipperAI/.venv/bin/klipperai-detect-profile \
  --config-file /home/<service-user>/printer_data/config/klipperai/klipperai.cfg \
  --moonraker-url http://127.0.0.1:7125 \
  --printer-data-root /home/<service-user>/printer_data \
  --overwrite
```

Then restart:

```bash
sudo systemctl restart klipperai-agent
```

You can also manually edit these sections in `klipperai.cfg`:

- `[printer_identity]`
- `[printer_capabilities]`
- `[config_context]`
- `[chat]`

For follow-up questions, `conversation_history_pairs` controls how many previous
user/assistant pairs from the current chat are sent with each request. The
default is `10`; set it to `0` to disable conversation context.

If this host still has an older `[printer_geometry]` section in `klipperai.cfg`, remove that section before restarting `klipperai-agent`.

## 11. Legacy Update Macro

The guided installer no longer offers `UPDATE_KLIPPERAI`, installs
`gcode_shell_command`, or edits `printer.cfg`. Use the Moonraker update-manager
integration to update the assistant. Existing macros are not removed by this
refactor; the separate `integrations/klipper/install-update-macro.sh` helper is
retained for legacy installations outside the supported guided flow.

For installer modules, access routes and automated verification commands, see
[frontend and installation ownership](frontend-and-installation.md).

## 12. Runtime Behavior

KlipperAI currently:

- reads current `.log` files under `printer_data/logs`
- sends only the configured last lines from each collected log file
- writes its own runtime log to `<data_dir>/logs/klipperai.log`
- reads current config files
- reads Moonraker state
- reads `systemctl` and `journalctl` data for Klipper and Moonraker
- proposes config snippets in chat

KlipperAI currently does **not**:

- write printer config files
- patch `printer.cfg`
- apply config proposals automatically

## 13. Troubleshooting

If the service does not start:

```bash
systemctl status klipperai-agent --no-pager
journalctl -u klipperai-agent -n 200 --no-pager
tail -n 200 /var/lib/klipperai/logs/klipperai.log
```

If Moonraker integration does not show up:

```bash
systemctl status moonraker --no-pager
journalctl -u moonraker -n 200 --no-pager
```

Check the generated files:

```bash
cat /etc/klipperai/klipperai.env
cat /home/<service-user>/printer_data/config/klipperai/klipperai.cfg
cat /home/<service-user>/printer_data/config/klipperai/klipperai-moonraker.cfg
cat /home/<service-user>/printer_data/moonraker.asvc
```

Check nginx:

```bash
sudo nginx -t
```

If clicking the Mainsail `KlipperAI` button opens a blank Mainsail page, check
whether `/klipperai/` is falling through to Mainsail instead of KlipperAI:

```bash
curl http://127.0.0.1:8811/healthz
curl http://127.0.0.1/klipperai/healthz
grep -R "klipperai\|nginx-location" /usr/data/nginx /etc/nginx 2>/dev/null
```

The first two commands should return JSON. If `/klipperai/healthz` returns
Mainsail HTML, add `include /etc/klipperai/nginx-location.conf;` inside the
active Mainsail nginx `server` block, then reload nginx.

## 14. Uninstall

To remove KlipperAI:

```bash
cd /home/<service-user>/KlipperAI
./uninstall.sh
```

Then reload nginx if needed and restart Moonraker:

```bash
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl restart moonraker
```

## Security and upgrades

Read [Security and local deployment](security.md) before exposing the UI remotely.
Sessions are not user authentication. Protect every `/klipperai/` route at the
proxy and keep the daemon on loopback.

The installer writes the provider environment file with mode `0600` and the
application data directory with mode `0700`. Keep keys out of the Mainsail-editable
`klipperai.cfg`; a key in that file now causes a startup validation error.
Runtime logs now live in `<data_dir>/logs/` (normally `/var/lib/klipperai/logs/`),
not the shared printer logs. Old shared logs and backups are not removed.
Review permissions and retained copies when upgrading. Diagnostic access and
existing collection limits remain unchanged.
