# Encrypted provider credentials

Standard Linux services use systemd 250+ (`systemd-creds` and `systemd-run`)
and an unprivileged account. Native Creality/KE services use the separate
[appliance credential backend](creality-compatibility.md): a root-only host wrapping
key, authenticated encrypted master and verified RAM-only delivery. There is no
plaintext-storage fallback. Neither host-key backend protects a complete disk image
containing its wrapping key; systemd can additionally use TPM binding.
The web page can start without an API key, but the agent remains unavailable.
Keys cannot be saved until the secure installer provisions a master credential.

## Storage and trust boundary

Provider keys are encrypted with AES-256-GCM using PyCryptodome's authenticated
encryption implementation (the isolated `pycryptodomex` namespace, with no Rust
runtime dependency). Every write gets a random 96-bit nonce and a 128-bit tag.
A versioned context is authenticated with the ciphertext. Authentication failure
never triggers a plaintext fallback or generates a replacement key.

The installed provider database is `<data_dir>/private/providers.sqlite3`, owned
by the service account, with directory mode 0700 and file mode 0600. Policy and
usage counters are non-secret; only the API-key field is encrypted. Symlinks,
hardlinks, special files and storage inside shared printer files are rejected.

The separate random 256-bit master key is encrypted by `systemd-creds` and stored
root-owned at `/etc/klipperai/credentials/provider-master.cred` (directory 0700,
file 0600). It is never stored next to the database in plaintext. The unit uses
`LoadCredentialEncrypted=klipperai-provider-master:...` to deliver the decrypted
master under `$CREDENTIALS_DIRECTORY` at startup. The application reads that
fixed credential name; it never adds the key to environment variables or model
tools. Master files must be regular, singly linked and private to the service UID.
`LimitCORE=0` also limits ordinary service core dumps.

Where `systemd-creds has-tpm2` confirms full support, creation explicitly requires
`host+tpm2`. Encryption errors abort setup. When TPM2 is unavailable, creation
uses the root-only systemd host key and prints that reduced protection explicitly.
An existing master is kept; reinstalling never silently replaces it. Existing
host-only credentials are not automatically re-bound after a hardware upgrade.

Host-key-only encryption does not protect a complete disk image containing both
the encrypted master and `/var/lib/systemd/credential.secret`. TPM binding can
prevent decryption of such a copy on another machine. Neither mode protects a
credential from root or a compromised running service. Other processes using the
same UID are also trusted: use a separate service account and protect executable
code ownership to obtain meaningful separation from other printer applications.
Do not assume existing shared printer accounts provide that separation.

## Install, upgrade and rotation

The installer disables tracing before reading a hidden key prompt, keeps the key
out of exported variables, and sends it through stdin to an unprivileged
transient systemd service. Master generation streams random bytes directly into
encryption; only ciphertext reaches a temporary file. No secret is placed in an
external command argument. The environment file contains deployment metadata,
including the provider storage path, but no API key.

Before migration, the installer stops KlipperAI alone. It uses the same encrypted
repository as Provider settings, preserving saved policy, revision checks and
usage counters. A previous home-based store, environment-selected store or
`provider_storage_dir` in the old config can be imported. Legacy plaintext DB
keys are encrypted before copying into the destination. The entered replacement
key updates the canonical store, so a stale saved key cannot override it.
After verifying the replacement, the obsolete source DB and its SQLite auxiliary
files are removed. Failed authentication keeps the original credential data.

After successful initialization the installer removes known API-key assignments
from the old environment file and its installer backups, before backing up the
remaining non-secret metadata. An environment key encountered by a manually
started application can be imported once into encrypted storage when a master is
available; saved removals still suppress fallback. Known key environment variables
are removed from the running process after provider initialization. Rerun the
installer to clean up root-owned legacy files.

UI rotation still validates before saving and takes effect after a manual restart.
The master stays fixed, so the web process can rotate encrypted API keys without
root access. Browser inputs clear after submission and closing; no read/export
endpoint returns credentials. New key submission requires HTTPS or a URL using
localhost/loopback (for an SSH tunnel). This transport check is not administrator
authentication. Protect the whole application with the authenticated proxy/tunnel
described in [security.md](security.md); sessions remain conversation handles.

Uninstall offers credential purge separately from conversation-data removal. It
removes known provider DBs and auxiliary files, the application's encrypted master
and installer environment backups. It never deletes systemd's global host key.
Retained external backups and old SD-card pages cannot be guaranteed erased;
revoke superseded provider keys when needed.

## Recovery and validation

Keep the original encrypted master and the relevant host/TPM binding when moving
an encrypted database. A lost master or unavailable TPM must produce a locked
store, not silent reset. A new installation on replacement hardware may require
entering a new provider key. Exclude credential artifacts from ordinary support
bundles; protect full system backups as secrets even when files are encrypted.

Automated tests cover authenticated encryption, nonce variation, tampering, missing
and wrong masters, file checks, migration, rotation, preserved counters, input
secrecy, installer command boundaries, cleanup and HTTP transport restrictions.
DOM tests cover transient keys and the locked-store explanation. These fixtures
do not prove real systemd/TPM enforcement. Before deployment, verify systemd
activation, actual ownership/modes, reboot, rotation and recovery on the target
Linux image with dummy credentials. Live provider and printer checks are separate.

Primary references, reviewed 2026-10-26:

- [PyCryptodome authenticated encryption and GCM](https://www.pycryptodome.org/src/cipher/modern#gcm-mode)
- [systemd credential delivery](https://systemd.io/CREDENTIALS/)
- [systemd-creds host/TPM encryption](https://www.freedesktop.org/software/systemd/man/latest/systemd-creds.html)
