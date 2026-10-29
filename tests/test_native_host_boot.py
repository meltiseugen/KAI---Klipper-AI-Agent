"""Real native process boot/update/rollback on Linux; no printer or provider network."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from deployment.appliance_config import ApplianceConfig
from deployment.appliance_credentials import ram_backed
from deployment.appliance_service import ApplianceService
from deployment.releases import ReleaseUpdater
from tests.release_helpers import ROOT, free_port, http


def test_native_process_boot_update_rollback_and_preserved_data(tmp_path):
    supported = (
        sys.platform.startswith("linux") and os.geteuid() == 0 and ram_backed(Path("/dev/shm"))
    )
    if not supported:
        if os.environ.get("KLIPPERAI_REQUIRE_NATIVE") == "1":
            pytest.fail("Native integration requires Linux root and a verified RAM filesystem.")
        pytest.skip("Linux root process integration runs separately in CI")
    install = tmp_path / "checkout"
    (install / ".venv/bin").mkdir(parents=True)
    # Use the test environment's installed dependencies; exec keeps the service PID.
    python = install / ".venv/bin/python"
    python.write_text(f"#!/bin/sh\nexec '{sys.executable}' \"$@\"\n")
    python.chmod(0o755)
    (install / "pyproject.toml").touch()
    shutil.copytree(
        ROOT / "deployment", install / "deployment", ignore=shutil.ignore_patterns("__pycache__")
    )
    port = free_port()
    environment = tmp_path / "service.env"
    values = {
        "CONFIG_FILE": str(tmp_path / "app.cfg"),
        "DATA_DIR": str(tmp_path / "data"),
        "PROVIDER_STORAGE_DIR": str(tmp_path / "data/private"),
        "PROJECT_CHECKOUT_PATH": str(install),
        "PRINTER_DATA_ROOT": str(tmp_path / "printer"),
        "MAINSAIL_CONFIG_DIR": str(tmp_path / "printer/config"),
        "HOST": "127.0.0.1",
        "PORT": str(port),
        "ROOT_PATH": "/klipperai",
        "MOONRAKER_URL": "http://127.0.0.1:1",
        "MOONRAKER_AGENT_ENABLED": "false",
        "COLLECT_SYSTEMD_DIAGNOSTICS": "false",
        "COLLECT_HOST_LOGS": "false",
    }
    environment.write_text(
        "".join(f"KLIPPERAI_{name}={json.dumps(value)}\n" for name, value in values.items())
    )
    printer = tmp_path / "printer/config/printer.cfg"
    printer.parent.mkdir(parents=True)
    printer.write_bytes(b"[printer]\nkinematics: cartesian\n")
    sentinel = tmp_path / "data/keep-history"
    sentinel.parent.mkdir()
    sentinel.write_bytes(b"saved application information")
    with tempfile.TemporaryDirectory(prefix="klipperai-native-test-", dir="/dev/shm") as directory:
        config = ApplianceConfig(
            install,
            environment,
            tmp_path / "host/key",
            tmp_path / "state/master.enc",
            Path(directory),
            "d" * 32,
        )
        config.credentials.provision()
        config.save()
        master = config.credentials.master()
        service = ApplianceService(config)
        updater = ReleaseUpdater(install, f"http://127.0.0.1:{port}/readyz", service=service)
        original_wait = updater.wait_ready
        updater.wait_ready = lambda expected: original_wait(expected, timeout=10)
        try:
            service.start()
            updater.wait_ready("source")
            pid = service.running()
            assert pid and pid != os.getpid()
            with http(f"http://127.0.0.1:{port}", "/api/ui-sessions", {}) as response:
                session = json.load(response)["session_id"]
            with http(
                f"http://127.0.0.1:{port}", "/api/bootstrap?session_id=" + session
            ) as response:
                assert json.load(response)["provider_configured"] is False
            release = updater.root / ("a" * 16)
            release.mkdir()
            shutil.copytree(
                ROOT / "klipperai_agent",
                release / "klipperai_agent",
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            shutil.copytree(
                ROOT / "deployment",
                release / "deployment",
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            (release / "klipperai_agent/build-info.json").write_text(
                json.dumps({"build": release.name})
            )
            updater.activate(release)
            assert updater.selected() == release and service.running() != pid
            broken = updater.root / ("b" * 16)
            shutil.copytree(release, broken)
            (broken / "klipperai_agent/build-info.json").write_text(
                json.dumps({"build": broken.name})
            )
            (broken / "klipperai_agent/__main__.py").write_text(
                'raise RuntimeError("simulated bad build")\n'
            )
            with pytest.raises(RuntimeError, match="restored"):
                updater.activate(broken)
            updater.wait_ready(release.name)
            assert updater.selected() == release
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "deployment.update",
                    "--install-dir",
                    str(install),
                    "--url",
                    updater.url,
                    "--rollback",
                ],
                cwd=ROOT,
                check=True,
                timeout=45,
            )
            updater.wait_ready("source")
            assert updater.selected() is None
            assert config.credentials.master() == master
            assert printer.read_bytes() == b"[printer]\nkinematics: cartesian\n"
            assert sentinel.read_bytes() == b"saved application information"
        finally:
            service.stop()
        assert service.running() is None
        assert not (config.runtime / "klipperai-provider-master").exists()
