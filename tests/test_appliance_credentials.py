"""Native host-key wrapping, authenticated reuse and tmpfs-only credential delivery."""

import json
import os
from pathlib import Path

import pytest

from deployment import appliance_credentials as credentials
from deployment.appliance_config import ApplianceConfig, environment_file


@pytest.fixture
def host_credentials(tmp_path):
    return credentials.HostCredentials(
        tmp_path / "host/host.key", tmp_path / "encrypted/master.enc"
    )


def test_appliance_master_is_encrypted_reused_and_never_reset(host_credentials):
    store = host_credentials
    store.provision()
    original = store.wrapped_master.read_bytes()
    master = store.master()
    assert len(master) == 32 and master not in original
    store.provision()
    assert store.wrapped_master.read_bytes() == original and store.master() == master
    store.host_key.unlink()
    with pytest.raises(OSError):
        store.provision()
    assert store.wrapped_master.read_bytes() == original
    assert not store.host_key.exists()


def test_wrong_host_key_and_tampering_preserve_ciphertext(host_credentials):
    store = host_credentials
    store.provision()
    original = store.wrapped_master.read_bytes()
    store.host_key.write_bytes(b"x" * 32)
    with pytest.raises(ValueError, match="authentication"):
        store.provision()
    assert store.wrapped_master.read_bytes() == original
    store.wrapped_master.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    with pytest.raises(ValueError, match="authentication"):
        store.master()


def test_missing_encrypted_master_never_regenerates_under_existing_host_key(host_credentials):
    store = host_credentials
    store.provision()
    original = store.host_key.read_bytes()
    store.wrapped_master.unlink()
    with pytest.raises(ValueError, match="missing"):
        store.provision()
    assert store.host_key.read_bytes() == original
    assert not store.wrapped_master.exists()


def test_delivery_refuses_disk_and_mismatched_ram_master(host_credentials, tmp_path, monkeypatch):
    store = host_credentials
    store.provision()
    runtime = tmp_path / "ram"
    monkeypatch.setattr(credentials, "ram_backed", lambda path: False)
    with pytest.raises(ValueError, match="tmpfs"):
        store.deliver(runtime)
    assert not runtime.exists()
    monkeypatch.setattr(credentials, "ram_backed", lambda path: True)
    assert store.deliver(runtime) == runtime
    path = runtime / credentials.MASTER_NAME
    assert path.read_bytes() == store.master()
    assert store.deliver(runtime) == runtime
    path.write_bytes(b"x" * 32)
    with pytest.raises(ValueError, match="differs"):
        store.deliver(runtime)
    assert path.read_bytes() == b"x" * 32


def test_ram_detection_uses_most_specific_mount_and_resolved_target(tmp_path):
    mounts = tmp_path / "mountinfo"
    # Windows roots have a drive prefix, but the parser accepts actual resolved fixture paths.
    root = Path(tmp_path.anchor).as_posix()
    parent = tmp_path.as_posix()
    mounts.write_text(
        f"1 0 0:1 / {root} rw - ext4 /dev/root rw\n2 1 0:2 / {parent} rw - tmpfs tmpfs rw\n3 2 0:3 / {parent}/disk rw - ext4 /dev/disk rw\n"
    )
    assert credentials.ram_backed(tmp_path / "runtime", mounts)
    assert not credentials.ram_backed(tmp_path / "disk/runtime", mounts)
    mounts.write_text("invalid\n")
    assert not credentials.ram_backed(tmp_path, mounts)


def test_private_files_reject_hardlinks_lengths_and_shared_permissions(tmp_path):
    key = tmp_path / "key"
    credentials.create_private(key, b"k" * 32)
    with pytest.raises(FileExistsError):
        credentials.create_private(key, b"replacement")
    with pytest.raises(ValueError, match="size"):
        credentials.read_private(key, 31)
    link = tmp_path / "hardlink"
    os.link(key, link)
    with pytest.raises(ValueError, match="singly"):
        credentials.read_private(key, 32)
    link.unlink()
    if os.name != "nt":
        key.chmod(0o644)
        with pytest.raises(ValueError, match="permissions"):
            credentials.read_private(key, 32)


def test_native_receipt_and_environment_are_metadata_only(tmp_path):
    install = tmp_path / "install"
    install.mkdir()
    config = ApplianceConfig(
        install,
        tmp_path / "app.env",
        tmp_path / "host/key",
        tmp_path / "state/wrapped",
        tmp_path / "ram",
        "a" * 32,
    )
    config.save()
    assert ApplianceConfig.load(install) == config
    config.save()
    receipt = install / ".klipperai-appliance.json"
    data = json.loads(receipt.read_text())
    data["install"] = str(tmp_path / "other")
    receipt.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="identity"):
        ApplianceConfig.load(install)
    env = config.environment
    env.write_text(
        '# metadata\nKLIPPERAI_CONFIG_FILE="/usr/data/printer_data/config/klipperai/klipperai.cfg"\nKLIPPERAI_SERVICE_USER="root"\n'
    )
    assert environment_file(env)["KLIPPERAI_SERVICE_USER"] == "root"
    env.write_text('KLIPPERAI_CONFIG_FILE="$(touch /outside)"\n')
    assert environment_file(env)["KLIPPERAI_CONFIG_FILE"] == "$(touch /outside)"
    env.write_text("KLIPPERAI_OPENAI_API_KEY=private\n")
    with pytest.raises(ValueError, match="non-secret"):
        environment_file(env)
