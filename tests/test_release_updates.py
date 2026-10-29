"""Transactions stage code first, preserve user data and recover a failed start."""

import json
import os
import subprocess
from pathlib import Path, PurePosixPath

import pytest

from deployment import releases
from tests.test_release_artifacts import wheel_file


def installation(tmp_path):
    install = tmp_path / "KlipperAI"
    (install / ".venv/bin").mkdir(parents=True)
    (install / ".venv/bin/python").touch()
    (install / "pyproject.toml").touch()
    return install


def managed(updater, name):
    target = updater.root / name
    (target / "klipperai_agent").mkdir(parents=True)
    (target / "klipperai_agent/build-info.json").write_text(json.dumps({"build": name}))
    return target


@pytest.fixture
def transaction(tmp_path, monkeypatch):
    commands, state = [], {"target": None}

    def execute(command, **kwargs):
        commands.append(command)
        if "--target" in command:
            (Path(command[command.index("--target") + 1]) / "klipperai_agent").mkdir()

    updater = releases.ReleaseUpdater(
        installation(tmp_path),
        "http://localhost/readyz",
        execute=execute,
        privileged=lambda command: commands.append(command),
        health=lambda _: {
            "status": "ok",
            "printer_access": "read_only",
            "build": state["target"].name if state["target"] else "source",
        },
    )
    monkeypatch.setattr(updater, "dropin", lambda: None)
    monkeypatch.setattr(updater, "selected", lambda: state["target"])
    monkeypatch.setattr(updater, "point", lambda target: state.update(target=target))
    return updater, commands, state


def test_code_only_stage_activate_rollback_and_retention(transaction, tmp_path):
    updater, commands, state = transaction
    outside = tmp_path / "printer-data"
    outside.mkdir()
    for name in ("printer.cfg", "provider-master.cred", "investigations.sqlite3"):
        (outside / name).write_bytes(b"preserve exactly")
    wheel, digest = wheel_file(tmp_path)
    target = updater.prepare(wheel, digest)
    install = commands[0]
    assert all(flag in install for flag in ("--no-index", "--no-deps", "--no-compile", "--target"))
    assert not updater.current.exists()  # Staging has not stopped or selected code.
    assert not any(command[0] == "systemctl" for command in commands)
    updater.activate(target)
    assert state["target"] == target
    assert json.loads(updater.previous.read_text()) == {"target": None}
    updater.rollback()
    assert state["target"] is None
    assert json.loads(updater.previous.read_text()) == {"target": target.name}
    updater.rollback()
    assert state["target"] == target
    older = managed(updater, "b" * 16)
    unrecognized = updater.root / ("c" * 16)
    unrecognized.mkdir()
    updater.prune()
    assert not older.exists() and unrecognized.exists()
    assert all(path.read_bytes() == b"preserve exactly" for path in outside.iterdir())
    service = [command for command in commands if command[0] == "systemctl"]
    assert all(
        command[1] in {"start", "stop"} and command[2] == releases.SERVICE for command in service
    )


def test_dependency_failure_removes_only_candidate_and_keeps_running_code(transaction, tmp_path):
    updater, commands, state = transaction
    old = managed(updater, "a" * 16)
    state["target"] = old
    wheel, digest = wheel_file(tmp_path)
    original = updater.execute

    def execute(command, **kwargs):
        if command[-2:] == ["pip", "check"]:
            raise subprocess.CalledProcessError(1, command)
        original(command, **kwargs)

    updater.execute = execute
    with pytest.raises(subprocess.CalledProcessError):
        updater.prepare(wheel, digest)
    assert state["target"] == old and old.is_dir()
    assert not (updater.root / digest[:16]).exists()
    assert not any(command[0] == "systemctl" for command in commands)


def test_prepared_release_is_rechecked_and_incomplete_stage_is_preserved(transaction, tmp_path):
    updater, commands, _ = transaction
    wheel, digest = wheel_file(tmp_path)
    target = updater.prepare(wheel, digest)
    commands.clear()
    assert updater.prepare(wheel, digest) == target
    assert len(commands) == 2 and commands[0][-2:] == ["pip", "check"]
    (target / "klipperai_agent/build-info.json").unlink()
    with pytest.raises(OSError):
        updater.prepare(wheel, digest)
    assert target.is_dir()  # Never remove unrecognized content from an earlier interruption.


def test_failed_start_restores_selection_and_receipt(transaction, monkeypatch):
    updater, commands, state = transaction
    old = managed(updater, "a" * 16)
    new = managed(updater, "b" * 16)
    state["target"] = old
    receipt = b'{"target": null}\n'
    updater.receipt(receipt)
    monkeypatch.setattr(
        updater, "wait_ready", lambda *args: (_ for _ in ()).throw(RuntimeError("not ready"))
    )
    with pytest.raises(RuntimeError, match="restored"):
        updater.activate(new)
    assert state["target"] == old and updater.previous.read_bytes() == receipt
    assert commands == [
        ["systemctl", action, releases.SERVICE] for action in ("stop", "start", "stop", "start")
    ]


def test_stop_failure_keeps_selection_and_existing_receipt(transaction):
    updater, _, state = transaction
    target = managed(updater, "a" * 16)
    updater.receipt(b'{"target": null}\n')

    def reject(command):
        raise RuntimeError("sudo failed")

    updater.privileged = reject
    with pytest.raises(RuntimeError, match="sudo"):
        updater.activate(target)
    assert state["target"] is None
    assert updater.previous.read_bytes() == b'{"target": null}\n'


def test_native_pointer_swap_and_unmanaged_content_are_safe(tmp_path):
    updater = releases.ReleaseUpdater(installation(tmp_path), "http://localhost/readyz")
    target = managed(updater, "a" * 16)
    try:
        updater.point(target)
    except OSError:
        if os.name == "nt":
            pytest.skip("Windows account lacks symlink privilege; Linux CI requires this check")
        raise
    assert updater.selected() == target
    updater.point(None)
    assert updater.selected() is None
    updater.current.mkdir()
    with pytest.raises(ValueError, match="unmanaged"):
        updater.point(target)
    assert updater.current.is_dir()


def test_readiness_times_out_on_wrong_build_and_accepts_original_install(transaction, monkeypatch):
    updater, _, _ = transaction
    with pytest.raises(RuntimeError, match="expected"):
        updater.wait_ready("wrong-build", timeout=0)
    updater.wait_ready("source", timeout=0)
    import urllib.error

    def legacy(url):
        if url.endswith("/readyz"):
            raise urllib.error.HTTPError(url, 404, "old checkout", {}, None)
        return {"status": "ok"}

    updater.health = legacy
    updater.wait_ready("source", timeout=0)


def test_dropin_refuses_to_replace_existing_operator_configuration(tmp_path, monkeypatch):
    updater = releases.ReleaseUpdater(installation(tmp_path), "http://localhost/readyz")
    if os.name == "nt":
        # Linux systemd values cannot contain a Windows drive prefix.
        updater.current = PurePosixPath("/home/printer/KlipperAI/.klipperai-releases/current")
    dropin = tmp_path / "managed.conf"
    monkeypatch.setattr(releases, "DROPIN", dropin)
    dropin.write_text("operator override")
    with pytest.raises(ValueError, match="drop-in differs"):
        updater.dropin()
    assert dropin.read_text() == "operator override"
