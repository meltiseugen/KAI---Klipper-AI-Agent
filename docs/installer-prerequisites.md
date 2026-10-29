# Automatic installer prerequisites

Run `sh install.sh` from a writable checkout on the printer host. Rooted
Creality/KE hosts run this command as root; standard Linux hosts need root or sudo.
Moonraker and Mainsail/Fluidd must already be installed. Network access and enough
persistent storage for packages, a virtual environment and any C build are required.
The installer does not provision printer firmware or replace the printer stack.

The POSIX entry point works before Bash or Python exists. It detects `opkg` under
`/opt`, apt or apk, installs Bash when missing, then starts the normal interactive
installation. `--help` never needs Bash. `--check` requires existing Bash and only
checks syntax; neither option installs packages.

## What setup installs

Only missing capabilities trigger package installation. A healthy installation
does not refresh a package index. During setup the index is refreshed once per
package manager, including across the initial Bash restart.

| Capability | Setup behavior |
| --- | --- |
| Bash | Installs through apt, opkg or apk before Bash scripts run. |
| Utilities and Git | Installs missing awk, find, grep, install, stat, tar and Git; repairs missing Git HTTPS helpers. |
| nginx | Keeps an existing vendor binary, including one outside PATH; installs nginx only if absent. |
| Python 3.10+ | Prefers supported `/opt` Python over older vendor Python; installs Python and required SSL, SQLite, ctypes and other standard-library modules plus pip. |
| Old apt-based Python | Runs the existing Python helper with one build job, using altinstall beside the distro interpreter when necessary. |
| Trusted HTTPS | Installs CA packages when Python cannot find trusted certificates; verifies Python's trust store afterward. |
| Virtual environment | Uses venv or virtualenv; installs the fallback helper into the checkout's `.local/installer-python`, leaving the vendor Python's global packages alone. |
| Encryption on native MIPS | Adds gcc, make and matching Python headers if the environment needs to build PyCryptodome; uses one make job. |

Package feeds must provide compatible packages. A failed transaction or an
unsupported interpreter stops installation with an error. Setup does not silently
substitute an incompatible Python or disable encrypted credential storage.

## Fresh Entware on Creality hosts

When vendor printer-data directories and native init exist but no package manager
does, setup can bootstrap the reviewed `mipselsf-k3.4` or `aarch64-k3.10` Entware feed.
MIPS must be little-endian. Base BusyBox utilities, including SHA-256, and an HTTPS
downloader must work. ARM64 also needs an existing working curl; native MIPS can
use the pinned Creality curl binary when the vendor curl is absent or broken.

The bootstrap creates `/usr/data/opt` and `/opt` only when their existing layout is
empty or already points there. It refuses to replace a different symlink or a
nonempty installation without usable opkg. A partial/broken existing Entware setup
needs repair; the installer preserves it instead of deleting it.

Bootstrap assets are SHA-256 pinned in
[`entware.sh`](../deployment/installer/entware.sh):

- Static opkg binaries from the official [MIPS](https://bin.entware.net/mipselsf-k3.4/installer/) and [ARM64](https://bin.entware.net/aarch64-k3.10/installer/) feeds.
- The dated [curl CA bundle](https://curl.se/ca/cacert-2026-10-20.pem), maintained through curl's [CA extract process](https://curl.se/docs/caextract.html).
- The MIPS curl fallback at a fixed [Creality Helper Script commit](https://github.com/Guilouz/Creality-Helper-Script/blob/7693c29676c0b138ec4f32b90d5c6f82bd2b2e13/files/fixes/curl).

Only these pinned assets can be fetched without an existing CA store: the digest
must match before any downloaded bytes are used. Package indexes and packages use
authenticated HTTPS with the verified CA bundle through a temporary wget adapter,
until Entware's wget/CA packages exist. No remote installer script is executed.
Existing package managers retain their own repository configuration.

A fresh bootstrap adds an Entware startup entry only if none exists. Entware and
its packages are shared prerequisites and remain when KlipperAI is uninstalled.
Existing Klipper, Moonraker and vendor nginx service scripts are preserved.

When upstream bootstrap assets change, installation fails on a digest mismatch.
Maintainers must review the new upstream binary, verify its architecture and hash,
update the pins and exercise a fresh printer installation. Refresh the dated CA
bundle through the same review. Do not remove digest verification to work around
a changed download.

Automated tests use disposable paths and simulated package managers/downloads.
Real package installation, CPU/ABI compatibility and boot remain part of
[KE hardware acceptance](creality-compatibility.md#validation-and-remaining-hardware-acceptance).
