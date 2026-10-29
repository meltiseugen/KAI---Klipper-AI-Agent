# Creality / Ender-3 V3 KE compatibility audit

Native rooted Creality/Ender-3 V3 KE installation, init service and SSH updates are
implemented. The original vendor-layout handling (`ca25bd8`, `1b7efb2`) remains.
The native path does not require systemd or sudo. Automated checks and a mandatory
Linux CI process test cover the implementation; actual KE firmware acceptance is
still pending. No live KE was connected during development.

## Install on the rooted printer

Use a rooted printer that already runs Moonraker and Mainsail/Fluidd. Keep the
checkout on persistent storage, for example `/usr/data/KlipperAI`, and run:

```sh
cd /usr/data/KlipperAI
sh install.sh
```

The installer automatically selects native init for the vendor printer-data layout
(including numbered roots) when real systemd is absent. It installs missing Bash,
Python 3.10+ and required modules, pip/virtualenv, Git HTTPS support, certificates,
utilities, and nginx if the vendor does not already provide it. `/opt/bin` and
`/opt/sbin` are detected without changing your shell profile. Native MIPS hosts
receive C build tools and Python headers when needed for encryption. The dependency
set avoids Rust builds and disables optional Python speedups.

If no package manager is present, setup bootstraps Entware on the reviewed
little-endian MIPS and ARM64 feeds. Existing nonempty `/opt` trees without a usable
opkg are preserved and reported for repair. See [prerequisites and bootstrap
provenance](installer-prerequisites.md) for requirements and pinned asset details.

The backend override remains available for unusual layouts:

```sh
KLIPPERAI_SERVICE_MANAGER=appliance sh install.sh
```

Run this path as root, matching native appliance service conventions. The selected
virtual environment's absolute Python path is used at boot. Package feeds and PyPI
must be reachable, and persistent storage must have space for dependencies and any
necessary C build. No manual Bash/Python installation or backend flag is normally
needed. Actual KE firmware installation remains a hardware acceptance check.

The application service is `/etc/init.d/S99klipperai`. A fresh Entware bootstrap
also installs its shared startup entry when none exists. Setup preserves
the existing Klipper/Moonraker service scripts. It keeps automatic log/config reads
and installs the same Mainsail link and nginx route. Systemd-only Mainsail/OE timers
are omitted on native hosts; the manual integration helpers remain available.

```sh
/etc/init.d/S99klipperai status
/etc/init.d/S99klipperai restart
tail -n 100 /usr/data/klipperai-data/logs/klipperai.log
```

The init entry starts KlipperAI at boot. There is no extra persistent Python
supervisor or periodic polling service. After a crash, use the restart command
and inspect the application's bounded rotating log.

## Fast fixes and rollback

Use [the SSH deployment workflow](printer-testing.md) with a root SSH target and
the actual checkout path. The updater detects the installed native receipt and
uses the native lifecycle. It stages only code, checks dependencies, verifies the
exact running build and restores the previous code on activation failure. Settings,
history and encrypted credentials stay in place. Shared dependencies are unchanged.

```json
{"printer": {"host": "root@printer.local", "install_dir": "/usr/data/KlipperAI", "url": "http://127.0.0.1:8811/readyz"}}
```

```sh
python -m tools.deploy printer
python -m tools.deploy printer --rollback
```

Run `bash uninstall.sh` from the checkout for removal. The native branch stops only
its recorded KlipperAI process and removes its own init entry. Credential purge and
data removal remain explicit choices; other printer services are preserved.

## Credentials and process ownership

API keys retain AES-256-GCM encryption. The native host stores an encrypted master
at `/usr/data/klipperai-host/provider-master.enc`, with a separate root-only wrapping
key at `/usr/data/.klipperai-host-key/host.key`. On boot it authenticates that master
and delivers the decrypted bytes through a private, verified tmpfs/ramfs directory.
No plaintext master is written to persistent storage. Missing/wrong keys or tampered
ciphertext fail closed and never reset saved credentials.

This is host-key protection without TPM binding: root or a complete disk image
containing both files can recover the key. The native daemon uses the appliance's
root account. Its LLM tools still expose only the existing validated read-only
capabilities; init, deployment and credential controls are operator commands with
no model tools or HTTP endpoints. A compromised root process remains trusted by the
host. Standard Linux hosts retain the unprivileged systemd/TPM-capable path.

Process stop checks the installation nonce and Linux process start time before
signaling a PID. It refuses an unrelated process or a reused PID. Core dumps are
disabled before the application starts.

## Retained behavior

| Special case | Implementation | Regression check |
| --- | --- | --- |
| `/usr/data/printer_data` and numbered printer data directories | `deployment/installer/discovery.sh` prefers vendor paths before home-directory defaults | Discovery against a disposable vendor tree |
| Moonraker under `/usr/data/printer_data/config` | Explicit config directory first, then vendor fallback | Both fallback and explicit override |
| Vendor nginx configuration paths and a bounded fallback search | `/usr/data/nginx/conf.d/`, `nginx.conf`, `conf/nginx.conf` | Every candidate and the search fallback |
| nginx binary outside PATH and an explicit `-c` configuration | `deployment/installer/nginx.sh` inspects the running nginx process and uses that binary/config for validation and reload | Simulated process evidence; invalid config prevents reload |
| Separate Fluidd/Mainsail server blocks | The include installer handles multiple server blocks; existing integration tests cover server scope and idempotence | `tests/test_installer.py` |
| OctoEverywhere under `/usr/data/octoeverywhere` | Vendor checkout discovery remains in `discovery.sh` | Lowercase and capitalized checkout names |
| Python without the standard `venv` module | `deployment/installer/python.sh` falls back to `virtualenv` | Virtual environment creation through that fallback |
| Missing Bash, package manager, Python modules or HTTPS support | POSIX bootstrap, preserved Entware layout and automatic prerequisite repair | `test_prerequisite_bootstrap.py`, `test_entware_bootstrap.py` |
| Low-resource dependency installation | Pydantic v1, no Rust-backed runtime dependencies; optional Python speedups disabled during installation | Existing dependency/install code; native binary availability still depends on host architecture |

The [Creality Helper Script's service installation](https://github.com/Guilouz/Creality-Helper-Script/blob/main/scripts/moonraker_nginx.sh)
uses init scripts and installs compatibility commands for host controls. Finding
`systemctl` on such an image does not establish support for real systemd credential
delivery. The native backend handles this case explicitly.

## Validation and remaining hardware acceptance

`test_creality_compatibility.py`, `test_appliance_credentials.py`,
`test_appliance_deployment.py` and `test_appliance_shell.py` cover layouts, backend
selection, credential authentication, input secrecy, native lifecycle and preservation.
`test_prerequisite_bootstrap.py` and `test_entware_bootstrap.py` exercise automatic
setup with disposable directories and fake package managers/downloads. They do not
install real packages or establish CPU/ABI compatibility on a KE.
`test_native_host_boot.py` runs actual Linux processes through startup, code update,
failed-build recovery and rollback; CI runs it as root with a required RAM filesystem.

Still verify on the actual KE: firmware/helper version, CPU/ABI and dependency
installation, real boot/reboot, RAM mount permissions, automatic evidence collection,
provider configuration, `/klipperai/`, update and rollback. Linux process tests do not
establish behavior on a particular vendor firmware image.
