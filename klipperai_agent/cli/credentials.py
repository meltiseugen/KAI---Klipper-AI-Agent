"""Installer-only credential initialization. Secrets enter through stdin only."""

from __future__ import annotations

import argparse
import configparser
import sqlite3
import sys
from pathlib import Path

from pydantic import SecretStr, ValidationError

from klipperai_agent.domain.provider_settings import ModelProfile, ProviderPolicy, ProviderUpdate
from klipperai_agent.infrastructure.credential_cipher import (
    CredentialStorageError,
    load_credential_cipher,
)
from klipperai_agent.infrastructure.provider_store import ProviderStore


def initialize_credentials(args: argparse.Namespace, raw_key: bytes) -> None:
    cipher = load_credential_cipher()
    if not cipher.available:
        raise CredentialStorageError("A host-delivered master credential is required.")
    policy = ProviderPolicy(provider=args.provider, agent=ModelProfile(model=args.model))
    key_text = raw_key.decode("ascii").rstrip("\r\n")
    candidate = ProviderUpdate(
        session_id="installer",
        revision=0,
        policy=policy,
        api_key=SecretStr(key_text) if key_text else None,
    )
    legacy_directory = args.legacy_storage_dir
    config_file = getattr(args, "legacy_config_file", None)
    if config_file and config_file.exists():
        config = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=("#", ";"))
        config.read(config_file, encoding="utf-8")
        for section in config.sections():
            override = config.get(section, "provider_storage_dir", fallback="").strip()
            if override:
                legacy_directory = Path(override).expanduser()
    store = ProviderStore(
        args.storage_dir,
        (
            args.checkout_dir,
            args.printer_data_root / "config",
            args.printer_data_root / "logs",
            args.printer_data_root / "gcodes",
        ),
        cipher=cipher,
    )
    store.migrate_from(legacy_directory)
    revision, saved, existing_key = store.load()
    if saved is None:
        profile = ModelProfile(model=args.model)
        policy = ProviderPolicy(
            provider=args.provider, agent=profile, search=profile, knowledge=profile, legacy=profile
        )
    else:
        policy = saved.copy(deep=True)
        policy.provider = args.provider
        policy.agent.model = args.model
    key = candidate.api_key.get_secret_value() if candidate.api_key else existing_key
    store.save(revision, policy, key)
    if store.load()[2] != key:
        raise CredentialStorageError("Credential storage verification failed.")
    # Do not retain a second credential database after verifying the replacement.
    if legacy_directory.resolve() != store.path.parent.resolve():
        legacy = legacy_directory / store.path.name
        for path in (
            legacy,
            *(Path(str(legacy) + suffix) for suffix in ("-journal", "-wal", "-shm")),
        ):
            if path.is_symlink() or (
                path.exists() and (not path.is_file() or path.stat().st_nlink != 1)
            ):
                raise CredentialStorageError("Unsafe legacy credential file; cleanup was refused.")
            path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Initialize encrypted provider credentials from stdin."
    )
    parser.add_argument("--storage-dir", required=True, type=Path)
    parser.add_argument("--legacy-storage-dir", required=True, type=Path)
    parser.add_argument("--legacy-config-file", type=Path)
    parser.add_argument("--checkout-dir", required=True, type=Path)
    parser.add_argument("--printer-data-root", required=True, type=Path)
    parser.add_argument("--provider", required=True, choices=("openai",))
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    try:
        raw_key = sys.stdin.buffer.read(1025)
        if len(raw_key) > 1024:
            raise ValueError
        initialize_credentials(args, raw_key)
    except (OSError, ValueError, sqlite3.Error, ValidationError, configparser.Error):
        print(
            "Encrypted credential setup failed; check storage, master credential and input. No secret values are printed.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    print("Encrypted provider credentials saved and verified.")


if __name__ == "__main__":
    main()
