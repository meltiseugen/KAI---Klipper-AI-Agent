"""Authenticated encryption; the master key is supplied by the host, never the DB."""

from __future__ import annotations

import base64
import binascii
import os
import stat
from pathlib import Path

from Cryptodome.Cipher import AES

PREFIX = "klipperai:aes256gcm:v1:"
CREDENTIAL_NAME = "klipperai-provider-master"
_CONTEXT = b"klipperai/provider-api-key/v1"


class CredentialStorageError(OSError):
    """A generic error that never includes a credential or crypto input."""


class CredentialCipher:
    def __init__(self, master: bytes | None):
        if master is not None and len(master) != 32:
            raise CredentialStorageError("Provider master credential must contain 32 bytes.")
        self._master = master

    @property
    def available(self) -> bool:
        return self._master is not None

    def _key(self) -> bytes:
        if self._master is None:
            raise CredentialStorageError(
                "Encrypted provider storage is locked. Run the installer to provision the host credential."
            )
        return self._master

    def encrypt(self, value: str) -> str:
        if not 1 <= len(value.encode("utf-8")) <= 2048:
            raise CredentialStorageError("Provider credential has an invalid size.")
        cipher = AES.new(self._key(), AES.MODE_GCM, nonce=os.urandom(12), mac_len=16)
        cipher.update(_CONTEXT)
        encrypted, tag = cipher.encrypt_and_digest(value.encode("utf-8"))
        return PREFIX + base64.b64encode(
            bytes(cipher.nonce) + bytes(tag) + bytes(encrypted)
        ).decode("ascii")

    def decrypt(self, value: str) -> str:
        key = self._key()
        try:
            if not value.startswith(PREFIX):
                raise ValueError
            payload = base64.b64decode(value[len(PREFIX) :], validate=True)
            if not 28 <= len(payload) <= 4096:
                raise ValueError
            cipher = AES.new(key, AES.MODE_GCM, nonce=payload[:12], mac_len=16)
            cipher.update(_CONTEXT)
            return cipher.decrypt_and_verify(payload[28:], payload[12:28]).decode("utf-8")
        except (ValueError, UnicodeError, binascii.Error):
            raise CredentialStorageError(
                "Provider credential could not be authenticated. Restore its original master credential; stored data was kept."
            ) from None


def load_credential_cipher() -> CredentialCipher:
    directory = os.environ.get("CREDENTIALS_DIRECTORY")
    if not directory:
        return CredentialCipher(None)
    path = Path(directory) / CREDENTIAL_NAME
    if any(parent.is_symlink() for parent in path.parents) or path.is_symlink():
        raise CredentialStorageError("Redirected provider master credentials are not allowed.")
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise CredentialStorageError(
                    "Provider master credential must be a regular private file."
                )
            if hasattr(os, "geteuid") and (
                metadata.st_mode & 0o077 or metadata.st_uid != os.geteuid()
            ):
                raise CredentialStorageError(
                    "Provider master credential has unsafe ownership or permissions."
                )
            master = stream.read(33)
    except OSError:
        raise CredentialStorageError(
            "Provider master credential is unavailable or unsafe."
        ) from None
    return CredentialCipher(master)
