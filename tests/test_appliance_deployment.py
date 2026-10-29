"""Native lifecycle, install and rollback use fixed application paths/actions."""

import argparse
import json
import signal
from types import SimpleNamespace

import pytest

from deployment import (
    appliance_credentials,
    appliance_install,
    appliance_service,
    appliance_uninstall,
)
from deployment.appliance_config import ApplianceConfig
from deployment.releases import ReleaseUpdater
from tests.test_release_updates import installation, managed


@pytest.fixture
def config(tmp_path):
    install = installation(tmp_path)
    config = ApplianceConfig(
        install,
        tmp_path / "app.env",
        tmp_path / "host/key",
        tmp_path / "state/wrapped",
        tmp_path / "ram",
        "a" * 32,
    )
    config.credentials.provision()
    config.save()
    return config


def test_native_process_receipt_never_targets_unrelated_pid(config, monkeypatch):
    service = appliance_service.ApplianceService(config)
    config.runtime.mkdir(mode=0o700)
    service.pidfile.write_text('{"pid":1,"start":null}')
    monkeypatch.setattr(appliance_service, "process_identity", lambda *args: None)
    assert service.running() is None
    service.pidfile.write_text('{"pid":123,"start":"before-reuse"}')
    monkeypatch.setattr(appliance_service, "process_identity", lambda *args: "after-reuse")
    monkeypatch.setattr(
        appliance_service.os, "kill", lambda *args: pytest.fail("unrelated process signaled")
    )
    service.stop()
    assert not service.pidfile.exists()


def test_native_start_and_stop_use_authenticated_process_identity(config, monkeypatch):
    monkeypatch.setattr(appliance_credentials, "ram_backed", lambda _: True)
    service = appliance_service.ApplianceService(config)
    process = SimpleNamespace(pid=123, poll=lambda: None)
    starts, signals = [], []

    def popen(command, **kwargs):
        starts.append((command, kwargs))
        return process

    monkeypatch.setattr(appliance_service.subprocess, "Popen", popen)
    monkeypatch.setattr(appliance_service, "process_identity", lambda pid, instance: "456")
    service.start()
    service.start()  # Idempotent while the same process is alive.
    assert len(starts) == 1
    assert starts[0][0][1:3] == ["-m", "deployment.appliance_runtime"]
    assert starts[0][1]["env"]["KLIPPERAI_NATIVE_INSTANCE"] == config.instance
    assert "CREDENTIALS_DIRECTORY" not in starts[0][1]["env"]

    def kill(pid, sig):
        signals.append((pid, sig))
        monkeypatch.setattr(appliance_service, "process_identity", lambda *args: None)

    monkeypatch.setattr(appliance_service.os, "kill", kill)
    service.stop()
    assert signals == [(123, signal.SIGTERM)]
    assert not service.pidfile.exists()
    assert not (config.runtime / "klipperai-provider-master").exists()


def test_native_release_activation_and_failed_build_restore_previous_code(config, monkeypatch):
    state = {"selected": None}
    commands = []
    service = SimpleNamespace(
        configure=lambda path: commands.append("configure"),
        stop=lambda: commands.append("stop"),
        start=lambda: commands.append("start"),
    )
    updater = ReleaseUpdater(
        config.install,
        "http://localhost/readyz",
        service=service,
        privileged=lambda *a: pytest.fail("systemd/sudo invoked"),
    )
    monkeypatch.setattr(updater, "selected", lambda: state["selected"])
    monkeypatch.setattr(updater, "point", lambda target: state.update(selected=target))
    monkeypatch.setattr(updater, "wait_ready", lambda *a: None)
    first = managed(updater, "b" * 16)
    updater.activate(first)
    second = managed(updater, "c" * 16)
    assert commands == ["configure", "stop", "start"]
    monkeypatch.setattr(
        updater, "wait_ready", lambda *a: (_ for _ in ()).throw(RuntimeError("new build failed"))
    )
    with pytest.raises(RuntimeError, match="restored"):
        updater.activate(second)
    assert state["selected"] == first and first.is_dir()
    assert json.loads(updater.previous.read_text()) == {"target": None}
    assert commands[-5:] == ["configure", "stop", "start", "stop", "start"]


def test_native_install_reuses_master_and_only_writes_own_init_script(
    config, tmp_path, monkeypatch
):
    monkeypatch.setattr(appliance_credentials, "ram_backed", lambda _: True)
    init = tmp_path / "S99klipperai"
    monkeypatch.setattr(appliance_install, "INIT_SCRIPT", init)
    args = argparse.Namespace(
        install_dir=config.install,
        environment_file=config.environment,
        state_dir=config.wrapped_master.parent,
        host_key_dir=config.host_key.parent,
        storage_dir=tmp_path / "data/private",
        legacy_storage_dir=tmp_path / "legacy",
        legacy_config_file=None,
        printer_data_root=tmp_path / "printer",
        checkout_dir=config.install,
        provider="openai",
        model="gpt-5.4-mini",
    )
    master = config.credentials.master()
    assert appliance_install.provision(args, b"example-provider-key") == config
    assert config.credentials.master() == master
    assert "example-provider-key" not in init.read_text()
    assert "deployment.appliance_service" in init.read_text()
    assert "systemctl" not in init.read_text() and "klipper.service" not in init.read_text()
    from klipperai_agent.infrastructure.credential_cipher import CredentialCipher
    from klipperai_agent.infrastructure.provider_store import ProviderStore

    db = ProviderStore(
        args.storage_dir, (config.install, args.printer_data_root), cipher=CredentialCipher(master)
    )
    assert db.load()[2] == "example-provider-key"
    assert b"example-provider-key" not in db.path.read_bytes()
    assert not (config.runtime / "klipperai-provider-master").exists()
    assert appliance_install.provision(args, b"") == config
    init.write_text("operator override")
    with pytest.raises(ValueError, match="differs"):
        appliance_install.provision(args, b"")
    assert init.read_text() == "operator override"


def test_native_uninstall_preserves_or_purges_exact_credentials(config, tmp_path, monkeypatch):
    init = tmp_path / "S99klipperai"
    init.write_text(appliance_install.init_script(config.install))
    unrelated = tmp_path / "S55klipper_service"
    unrelated.write_text("preserve")
    monkeypatch.setattr(appliance_uninstall, "INIT_SCRIPT", init)
    appliance_uninstall.remove(config.install)
    assert not init.exists() and config.host_key.exists() and config.wrapped_master.exists()
    assert unrelated.read_text() == "preserve"
    appliance_uninstall.remove(config.install, purge=True)
    assert not config.host_key.exists() and not config.wrapped_master.exists()
    assert unrelated.read_text() == "preserve"


def test_first_native_install_provisions_reusable_ciphertext_and_boot_entry(tmp_path, monkeypatch):
    install = installation(tmp_path)
    monkeypatch.setattr(appliance_credentials, "ram_backed", lambda _: True)
    monkeypatch.setattr(appliance_install, "ram_backed", lambda _: True)
    init = tmp_path / "S99klipperai"
    monkeypatch.setattr(appliance_install, "INIT_SCRIPT", init)
    args = argparse.Namespace(
        install_dir=install,
        environment_file=tmp_path / "app.env",
        state_dir=tmp_path / "host-state",
        host_key_dir=tmp_path / "host-key",
        runtime_dir=tmp_path / "ram",
        storage_dir=tmp_path / "data/private",
        legacy_storage_dir=tmp_path / "legacy",
        legacy_config_file=None,
        printer_data_root=tmp_path / "printer",
        checkout_dir=install,
        provider="openai",
        model="gpt-5.4-mini",
    )
    config = appliance_install.provision(args, b"example-native-key")
    assert config == ApplianceConfig.load(install)
    encrypted = config.wrapped_master.read_bytes()
    assert config.credentials.master() not in encrypted
    assert "current" in init.read_text()
    assert appliance_install.provision(args, b"") == config
    assert config.wrapped_master.read_bytes() == encrypted
