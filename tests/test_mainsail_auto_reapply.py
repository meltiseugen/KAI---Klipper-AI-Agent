from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "integrations/mainsail"


def test_hook_retains_settings_checks_at_boot_and_removes_cleanly(
    mainsail_maintenance, tmp_path, monkeypatch
):
    m = mainsail_maintenance
    units = tmp_path / "systemd"
    ownership = []
    monkeypatch.setattr(os, "chown", lambda *args: ownership.append(args), raising=False)
    monkeypatch.setenv("KLIPPERAI_SYSTEMD_DIR", str(units))
    monkeypatch.setitem(
        sys.modules, "pwd", SimpleNamespace(getpwuid=lambda uid: SimpleNamespace(pw_name="printer"))
    )
    commands = []
    monkeypatch.setattr(m.hook, "systemctl", lambda *args: commands.append(args))
    assert (
        m.cli.main(
            m.args
            + [
                "--install-hook",
                "--title",
                "My Assistant",
                "--href",
                "/assistant/printer/",
                "--target",
                "_self",
                "--icon",
                "M0 0Z",
                "--interval",
                "7min",
            ]
        )
        == 0
    )
    timer = (units / "klipperai-mainsail-reapply.timer").read_text()
    assert "OnBootSec=30s" in timer and "WantedBy=timers.target" in timer
    assert "OnUnitInactiveSec=7min" in timer
    service = (units / "klipperai-mainsail-reapply.service").read_text()
    assert "User=printer" in service and "--reconcile" in service
    assert "settings.json" in service and "TimeoutStartSec=60" in service
    assert (
        f"PathChanged={m.files.path.as_posix()}\n"
        in (units / "klipperai-mainsail-reapply.path").read_text()
    )
    assert (
        "enable",
        "--now",
        "klipperai-mainsail-reapply.timer",
        "klipperai-mainsail-reapply.path",
    ) in commands
    assert commands[-1] == ("start", "klipperai-mainsail-reapply.service")
    assert (m.state, m.config.stat().st_uid, m.config.stat().st_gid) in ownership
    assert (
        m.state / "maintenance.lock",
        m.config.stat().st_uid,
        m.config.stat().st_gid,
    ) in ownership
    # Saved settings, not HOME or ambient shell variables, determine repair behavior.
    monkeypatch.delenv("HOME", raising=False)
    args = ["--settings-file", str(m.state / "settings.json"), "--reconcile"]
    assert m.cli.main(args) == 0
    assert json.loads(m.files.path.read_bytes()) == [
        {
            "title": "My Assistant",
            "href": "/assistant/printer/",
            "target": "_self",
            "position": 85,
            "icon": "M0 0Z",
        }
    ]
    assert m.cli.main(["--remove-hook"]) == 0
    assert not list(units.iterdir())
    assert m.files.path.exists()  # Removing automation does not remove the link.


def test_hook_validation_and_initial_failure_keep_retry_units(mainsail_maintenance, monkeypatch):
    m = mainsail_maintenance
    for options in (["--user", "bad user"], ["--user", "printer", "--interval", "0s"]):
        assert m.cli.main(m.args + ["--install-hook", *options]) == 1
    assert not m.state.exists()
    with pytest.raises(ValueError, match="Systemd paths"):
        m.hook.unit_path(Path("bad%path"))
    assert m.hook.unit_path(Path("/home/printer data/config")) == "/home/printer data/config"
    assert (
        m.hook.unit_path(Path("/home/printer data/config"), True) == '"/home/printer data/config"'
    )
    commands = []

    def systemctl(*args):
        commands.append(args)
        if args[0] == "start":
            raise subprocess.CalledProcessError(1, "systemctl")

    monkeypatch.setattr(m.hook, "systemctl", systemctl)
    monkeypatch.setenv("KLIPPERAI_SYSTEMD_DIR", str(m.config.parent / "units"))
    assert m.cli.main(m.args + ["--install-hook", "--user", "printer"]) == 0
    assert any(args[0] == "enable" for args in commands)
    assert (m.config.parent / "units/klipperai-mainsail-reapply.timer").exists()


def test_fixed_bounded_systemctl_adapter(mainsail_maintenance, monkeypatch):
    run = Mock()
    monkeypatch.setattr(mainsail_maintenance.hook.subprocess, "run", run)
    mainsail_maintenance.hook.systemctl("start", "klipperai-mainsail-reapply.service")
    assert run.call_args.args[0][-2:] == ["start", "klipperai-mainsail-reapply.service"]
    assert run.call_args.kwargs == {"check": True, "timeout": 60}


def test_shell_install_and_remove_keep_settings_and_do_not_touch_printer(
    mainsail_maintenance, tmp_path, run_shell, shell_env
):
    m = mainsail_maintenance
    units = tmp_path / "units"
    env = {**shell_env, "KLIPPERAI_SYSTEMD_DIR": units.as_posix()}
    args = ["--config-dir", m.config.as_posix(), "--href", "/assistant/printer/"]
    run_shell(INTEGRATION / "install-custom-nav.sh", *args, env=env)
    run_shell(INTEGRATION / "install-auto-reapply.sh", *args, "--user", "printer", env=env)
    m.files.path.unlink()  # An updater/restore replaced our navigation file.
    run_shell(
        INTEGRATION / "run-nav.sh",
        "--settings-file",
        m.state / "settings.json",
        "--reconcile",
        env=env,
    )
    assert json.loads(m.files.path.read_bytes())[0]["href"] == "/assistant/printer/"
    run_shell(INTEGRATION / "uninstall-custom-nav.sh", *args, env=env)
    run_shell(
        INTEGRATION / "run-nav.sh",
        "--settings-file",
        m.state / "settings.json",
        "--reconcile",
        env=env,
    )
    assert json.loads(m.files.path.read_bytes()) == []
    run_shell(INTEGRATION / "uninstall-auto-reapply.sh", env=env)
    assert not list(units.iterdir())
