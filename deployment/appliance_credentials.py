"""Host-key encryption and RAM-only master delivery for native appliance services."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from Cryptodome.Cipher import AES

HEADER = b"KAIHOST1"
CONTEXT = b"klipperai/appliance-master/v1"
MASTER_NAME = "klipperai-provider-master"


def protect_process() -> None:
    import resource

    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def private_directory(path: Path) -> None:
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("Credential directories must not be redirected.")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if os.name != "nt" and (info.st_uid != os.geteuid() or info.st_mode & 0o077):
        raise ValueError("Credential directories must be private to the service account.")


def read_private(path: Path, size: int) -> bytes:
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("Redirected credential files are refused.")
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    )
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Credential must be a singly linked regular file.")
        if os.name != "nt" and (info.st_uid != os.geteuid() or info.st_mode & 0o077):
            raise ValueError("Credential permissions or ownership are unsafe.")
        data = stream.read(size + 1)
    if len(data) != size:
        raise ValueError("Credential has an invalid size.")
    return data


def create_private(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def ram_backed(path: Path, mountinfo: Path = Path("/proc/self/mountinfo")) -> bool:
    target = path.resolve()
    mounts = []
    for line in mountinfo.read_text().splitlines():
        left, _, right = line.partition(" - ")
        fields = left.split()
        if len(fields) >= 5 and right:
            mount = Path(fields[4].replace("\\040", " ").replace("\\134", "\\"))
            if target.is_relative_to(mount):
                mounts.append((len(mount.parts), right.split()[0]))
    return bool(mounts and max(mounts)[1] in {"tmpfs", "ramfs"})


class HostCredentials:
    def __init__(self, host_key: Path, wrapped_master: Path):
        self.host_key, self.wrapped_master = host_key, wrapped_master
        if host_key.parent == wrapped_master.parent:
            raise ValueError("Store the wrapping key separately from encrypted credentials.")

    def provision(self) -> None:
        private_directory(self.host_key.parent)
        private_directory(self.wrapped_master.parent)
        if self.wrapped_master.exists() or self.wrapped_master.is_symlink():
            self.master()  # Authenticate existing data; never replace a missing/wrong key.
            return
        if self.host_key.exists() or self.host_key.is_symlink():
            raise ValueError(
                "Encrypted master is missing; preserve the host key and restore the original credential."
            )
        if not self.host_key.exists():
            create_private(self.host_key, os.urandom(32))
        key = read_private(self.host_key, 32)
        cipher = AES.new(key, AES.MODE_GCM, nonce=os.urandom(12), mac_len=16)
        cipher.update(CONTEXT)
        encrypted, tag = cipher.encrypt_and_digest(os.urandom(32))
        create_private(self.wrapped_master, HEADER + cipher.nonce + tag + encrypted)
        self.master()

    def master(self) -> bytes:
        key = read_private(self.host_key, 32)
        data = read_private(self.wrapped_master, len(HEADER) + 60)
        try:
            if not data.startswith(HEADER):
                raise ValueError
            payload = data[len(HEADER) :]
            cipher = AES.new(key, AES.MODE_GCM, nonce=payload[:12], mac_len=16)
            cipher.update(CONTEXT)
            return cipher.decrypt_and_verify(payload[28:], payload[12:28])
        except ValueError:
            raise ValueError(
                "Appliance master authentication failed; original credentials were preserved."
            ) from None

    def deliver(self, runtime: Path) -> Path:
        if not ram_backed(runtime):
            raise ValueError(
                "Decrypted master delivery requires a tmpfs or ramfs runtime directory."
            )
        private_directory(runtime)
        path = runtime / MASTER_NAME
        master = self.master()
        if path.exists() or path.is_symlink():
            if read_private(path, 32) != master:
                raise ValueError("Runtime master differs; refusing to replace it.")
        else:
            create_private(path, master)
        return runtime
