import argparse
import base64
import io
import os
import sqlite3
import stat
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from klipperai_agent.cli import credentials as cli
from klipperai_agent.domain.provider_settings import ProviderPolicy
from klipperai_agent.infrastructure import credential_cipher as crypto
from klipperai_agent.infrastructure.provider_store import ProviderStore


def arguments(tmp_path, **overrides):
    return argparse.Namespace(
        **{
            "storage_dir": tmp_path / "private",
            "legacy_storage_dir": tmp_path / "legacy",
            "checkout_dir": tmp_path / "checkout",
            "printer_data_root": tmp_path / "printer",
            "provider": "openai",
            "model": "selected-model",
            **overrides,
        }
    )


def test_authenticated_encryption_is_randomized_and_fails_closed():
    cipher = crypto.CredentialCipher(b"x" * 32)
    encrypted = cipher.encrypt("private-api-secret")
    assert encrypted.startswith(crypto.PREFIX)
    assert "private-api-secret" not in encrypted
    assert encrypted != cipher.encrypt("private-api-secret")
    assert cipher.decrypt(encrypted) == "private-api-secret"
    payload = bytearray(base64.b64decode(encrypted[len(crypto.PREFIX) :]))
    payload[-1] ^= 1
    invalid = [
        "plaintext",
        crypto.PREFIX + "?",
        crypto.PREFIX + "YQ==",
        crypto.PREFIX + base64.b64encode(payload).decode(),
    ]
    for value in invalid:
        with pytest.raises(crypto.CredentialStorageError, match="authenticated") as error:
            cipher.decrypt(value)
        assert "private-api-secret" not in str(error.value)
    with pytest.raises(crypto.CredentialStorageError):
        crypto.CredentialCipher(b"y" * 32).decrypt(encrypted)
    for value in ("", "x" * 2049):
        with pytest.raises(crypto.CredentialStorageError, match="size"):
            cipher.encrypt(value)
    with pytest.raises(crypto.CredentialStorageError, match="32 bytes"):
        crypto.CredentialCipher(b"short")


def test_master_is_required_and_never_generated_next_to_the_database(tmp_path, monkeypatch):
    monkeypatch.delenv("CREDENTIALS_DIRECTORY")
    cipher = crypto.load_credential_cipher()
    assert not cipher.available
    store = ProviderStore(tmp_path / "private", ())
    assert not store.credential_storage_available
    store.save(0, ProviderPolicy(), None)
    with pytest.raises(crypto.CredentialStorageError, match="locked"):
        store.save(1, ProviderPolicy(), "never-save-plaintext")
    assert store.load() == (1, ProviderPolicy(), None)
    assert {path.name for path in store.path.parent.iterdir()} == {"providers.sqlite3"}
    with pytest.raises(crypto.CredentialStorageError):
        cipher.decrypt("anything")


def test_master_file_read_is_bounded_and_rejects_redirection_and_unsafe_metadata(monkeypatch):
    directory = Path(os.environ["CREDENTIALS_DIRECTORY"])
    master = directory / crypto.CREDENTIAL_NAME
    assert crypto.load_credential_cipher().available
    master.write_bytes(b"x" * 33)
    with pytest.raises(crypto.CredentialStorageError, match="32 bytes"):
        crypto.load_credential_cipher()
    master.write_bytes(b"x" * 32)
    original = Path.is_symlink
    with monkeypatch.context() as patch:
        patch.setattr(Path, "is_symlink", lambda path: path == master or original(path))
        with pytest.raises(crypto.CredentialStorageError, match="Redirected"):
            crypto.load_credential_cipher()
    for metadata in (
        SimpleNamespace(st_mode=stat.S_IFDIR, st_nlink=1),
        SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_nlink=1, st_uid=0),
        SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_nlink=1, st_uid=1),
        SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_nlink=2),
    ):
        with monkeypatch.context() as patch:
            patch.setattr(crypto.os, "fstat", lambda fd: metadata)
            patch.setattr(crypto.os, "geteuid", lambda: 0, raising=False)
            with pytest.raises(crypto.CredentialStorageError, match="unsafe"):
                crypto.load_credential_cipher()
    master.unlink()
    with pytest.raises(crypto.CredentialStorageError, match="unavailable"):
        crypto.load_credential_cipher()


def test_plaintext_store_is_migrated_without_resetting_policy_usage_or_revision(tmp_path):
    source = ProviderStore(tmp_path / "legacy", ())
    policy = ProviderPolicy(provider="openai", requests_per_day=99)
    source.save(0, policy, "legacy-api-secret")
    source.reserve(policy, 120)
    with closing(sqlite3.connect(source.path)) as db, db:
        db.execute("UPDATE settings SET api_key='legacy-api-secret'")
    target = ProviderStore(tmp_path / "private", ())
    target.migrate_from(source.path.parent)
    assert target.load() == (1, policy, "legacy-api-secret")
    assert target.usage()["requests"] == 1 and target.usage()["tokens"] == 120
    assert b"legacy-api-secret" not in target.path.read_bytes()
    assert b"legacy-api-secret" not in source.path.read_bytes()
    target.migrate_from(target.path.parent)
    target.save(1, ProviderPolicy(), None)
    target.migrate_from(source.path.parent)
    assert target.load() == (2, ProviderPolicy(), None)


def test_missing_or_wrong_master_preserves_legacy_or_encrypted_credentials(tmp_path, monkeypatch):
    store = ProviderStore(tmp_path / "private", ())
    store.save(0, ProviderPolicy(), "existing-api-secret")
    before = store.path.read_bytes()
    with pytest.raises(crypto.CredentialStorageError):
        ProviderStore(store.path.parent, (), cipher=crypto.CredentialCipher(b"z" * 32))
    assert store.path.read_bytes() == before
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute("UPDATE settings SET api_key='legacy-api-secret'")
    monkeypatch.delenv("CREDENTIALS_DIRECTORY")
    with pytest.raises(crypto.CredentialStorageError, match="locked"):
        ProviderStore(store.path.parent, ())
    with closing(sqlite3.connect(store.path)) as db:
        assert db.execute("SELECT api_key FROM settings").fetchone()[0] == "legacy-api-secret"


def test_installer_replacement_preserves_policy_usage_and_removes_legacy_copy(tmp_path):
    args = arguments(tmp_path)
    legacy = ProviderStore(args.legacy_storage_dir, ())
    policy = ProviderPolicy(provider="openai", requests_per_day=99)
    policy.search.model = "custom-search-model"
    legacy.save(0, policy, "old-api-secret")
    legacy.reserve(policy, 120)
    cli.initialize_credentials(args, b"new-api-secret\n")
    store = ProviderStore(args.storage_dir, ())
    revision, saved, key = store.load()
    assert revision == 2 and key == "new-api-secret"
    assert saved.search.model == "custom-search-model" and saved.requests_per_day == 99
    assert saved.agent.model == args.model and store.usage()["requests"] == 1
    assert not legacy.path.exists()
    assert b"new-api-secret" not in store.path.read_bytes()
    cli.initialize_credentials(arguments(tmp_path), b"")
    assert store.load()[2] == "new-api-secret"


def test_installer_same_store_fresh_policy_input_errors_and_locked_storage(tmp_path, monkeypatch):
    args = arguments(tmp_path)
    args.legacy_storage_dir = args.storage_dir
    cli.initialize_credentials(args, b"new-api-secret")
    assert ProviderStore(args.storage_dir, ()).load()[1].search.model == args.model
    cli.initialize_credentials(args, b"")
    assert ProviderStore(args.storage_dir, ()).load()[2] == "new-api-secret"
    with pytest.raises(ValueError):
        cli.initialize_credentials(args, b"key with whitespace")
    monkeypatch.delenv("CREDENTIALS_DIRECTORY")
    with pytest.raises(crypto.CredentialStorageError, match="host-delivered"):
        cli.initialize_credentials(args, b"new-api-secret")


def test_installer_migrates_custom_configured_store_without_overwriting_other_policy(tmp_path):
    args = arguments(tmp_path)
    args.legacy_config_file = tmp_path / "klipperai.cfg"
    directory = tmp_path / "custom-private"
    args.legacy_config_file.write_text(
        f"[server]\nport: 8811\n[llm]\nprovider_storage_dir: {directory.as_posix()}\n"
    )
    source = ProviderStore(directory, ())
    source.save(0, ProviderPolicy(requests_per_day=77), "old-api-secret")
    cli.initialize_credentials(args, b"new-api-secret")
    assert ProviderStore(args.storage_dir, ()).load()[1].requests_per_day == 77
    assert not source.path.exists()


def test_migration_and_cleanup_keep_the_canonical_database_when_paths_are_aliases(
    tmp_path, monkeypatch
):
    args = arguments(tmp_path)
    cli.initialize_credentials(args, b"first-api-secret")
    nested = args.storage_dir / "nested"
    nested.mkdir()
    args.legacy_storage_dir = nested / ".."
    store = ProviderStore(args.storage_dir, ())
    with monkeypatch.context() as patch:
        patch.setattr(
            ProviderStore,
            "_connect",
            lambda self: pytest.fail("Must not back up a database into itself"),
        )
        store.migrate_from(args.legacy_storage_dir)
    cli.initialize_credentials(args, b"replacement-api-secret")
    assert store.path.exists()
    assert store.load()[2] == "replacement-api-secret"


def test_installer_verification_and_unsafe_cleanup_fail_without_printing_secrets(
    tmp_path, monkeypatch
):
    args = arguments(tmp_path)
    original = ProviderStore.load
    count = 0

    def mismatch(store):
        nonlocal count
        count += 1
        return original(store) if count == 1 else (1, ProviderPolicy(), "unexpected")

    with monkeypatch.context() as patch:
        patch.setattr(ProviderStore, "load", mismatch)
        with pytest.raises(crypto.CredentialStorageError, match="verification"):
            cli.initialize_credentials(args, b"new-api-secret")
    original_link = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == args.legacy_storage_dir / "providers.sqlite3" or original_link(path),
    )
    with pytest.raises(crypto.CredentialStorageError, match="Unsafe legacy"):
        cli.initialize_credentials(args, b"new-api-secret")


@pytest.mark.parametrize(
    "input_bytes,success", [(b"new-api-secret", True), (b"x" * 1025, False), (b"\xff", False)]
)
def test_installer_cli_keeps_stdin_secret_out_of_output(
    tmp_path, monkeypatch, capsys, input_bytes, success
):
    args = arguments(tmp_path)
    argv = ["credentials"]
    for name, value in vars(args).items():
        argv.extend(["--" + name.replace("_", "-"), str(value)])
    monkeypatch.setattr(cli.sys, "argv", argv)
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(input_bytes)))
    if success:
        cli.main()
    else:
        with pytest.raises(SystemExit) as error:
            cli.main()
        assert error.value.code == 1
    output = capsys.readouterr()
    assert "new-api-secret" not in output.out + output.err
