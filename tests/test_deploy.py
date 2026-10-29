"""Operator deployment transport never sends local settings, logs or credentials."""

import io
import json
import tarfile
from types import SimpleNamespace

import pytest

from deployment import update
from tests.test_release_artifacts import wheel_file
from tools import deploy


@pytest.mark.parametrize(
    "host,install,url",
    [
        ("-oProxyCommand=bad", "/home/pi/KlipperAI", "http://127.0.0.1:8811/readyz"),
        ("printer", "/home/pi/../printer", "http://127.0.0.1:8811/readyz"),
        ("printer", "/home/pi/a b", "http://127.0.0.1:8811/readyz"),
        ("printer", "/home/pi/KlipperAI", "https://example.com/readyz"),
        ("printer", "/home/pi/KlipperAI", "http://secret@localhost/readyz"),
        ("printer", "/home/pi/KlipperAI", "http://localhost/readyz?secret=yes"),
    ],
)
def test_deploy_rejects_ambiguous_targets_before_any_command(monkeypatch, host, install, url):
    monkeypatch.setattr(deploy, "run", lambda *a, **k: pytest.fail("unexpected transport"))
    with pytest.raises(ValueError):
        deploy.deploy(host, install, url, rollback=True)


def test_workspace_build_upload_activate_and_private_cleanup(tmp_path, monkeypatch):
    wheel, checksum = wheel_file(tmp_path)
    calls, cleanup, bundles = [], [], []
    monkeypatch.setattr(deploy, "build_wheel", lambda _: wheel)

    def execute(command, **kwargs):
        calls.append(command)
        if "input" in kwargs:
            bundles.append(kwargs["input"])
        return SimpleNamespace(stdout="/tmp/klipperai-deploy.abcdefgh\n")

    monkeypatch.setattr(deploy, "run", execute)
    monkeypatch.setattr(deploy.subprocess, "run", lambda command, **kwargs: cleanup.append(command))
    deploy.deploy("pi@printer", "/home/pi/KlipperAI", "http://127.0.0.1:8811/readyz")
    assert not any(command[0] == "scp" for command in calls)
    assert len(bundles) == 1
    with tarfile.open(fileobj=io.BytesIO(bundles[0])) as archive:
        assert archive.getnames() == [
            "deployment/update.py",
            "deployment/releases.py",
            "deployment/artifacts.py",
            "deployment/appliance_config.py",
            "deployment/appliance_credentials.py",
            "deployment/appliance_service.py",
            wheel.name,
        ]
        assert archive.extractfile(wheel.name).read() == wheel.read_bytes()
    activate = calls[-1]
    assert activate[:3] == ["ssh", "-t", "pi@printer"]
    assert "-m deployment.update" in activate[-1] and checksum in activate[-1]
    assert cleanup == [["ssh", "pi@printer", "rm -rf -- /tmp/klipperai-deploy.abcdefgh"]]


def test_dry_run_rollback_and_failed_remote_paths(tmp_path, monkeypatch):
    wheel, _ = wheel_file(tmp_path)
    monkeypatch.setattr(deploy, "run", lambda *a, **k: pytest.fail("dry run contacted host"))
    deploy.deploy(
        "printer", "/home/pi/KlipperAI", "http://localhost:8811/readyz", wheel=wheel, dry_run=True
    )
    with pytest.raises(ValueError, match="Choose"):
        deploy.deploy(
            "printer", "/home/pi/KlipperAI", "http://localhost/readyz", wheel=wheel, rollback=True
        )
    calls = []
    monkeypatch.setattr(deploy, "build_wheel", lambda _: pytest.fail("rollback built code"))
    monkeypatch.setattr(
        deploy,
        "run",
        lambda command, **kwargs: (
            calls.append(command) or SimpleNamespace(stdout="/tmp/klipperai-deploy.abc")
        ),
    )
    monkeypatch.setattr(deploy.subprocess, "run", lambda *a, **k: None)
    deploy.deploy(
        "printer",
        "/home/pi/KlipperAI",
        "http://localhost/readyz",
        rollback=True,
        non_interactive=True,
    )
    assert calls[-1][:2] == ["ssh", "-T"]
    assert "--rollback --non-interactive" in calls[-1][-1]
    assert len([command for command in calls if "tar -xf" in command[-1]]) == 1
    monkeypatch.setattr(deploy, "run", lambda *a, **k: SimpleNamespace(stdout="/home/pi"))
    with pytest.raises(ValueError, match="temporary"):
        deploy.deploy("printer", "/home/pi/KlipperAI", "http://localhost/readyz", rollback=True)


def test_deploy_cleans_only_its_staging_directory_on_transport_failure(monkeypatch):
    calls = []

    def execute(command, **kwargs):
        if "mktemp" in command[-1]:
            return SimpleNamespace(stdout="/tmp/klipperai-deploy.abc")
        raise RuntimeError("transport failed")

    monkeypatch.setattr(deploy, "run", execute)
    monkeypatch.setattr(deploy.subprocess, "run", lambda command, **kwargs: calls.append(command))
    with pytest.raises(RuntimeError, match="transport"):
        deploy.deploy("printer", "/home/pi/KlipperAI", "http://localhost/readyz", rollback=True)
    assert calls == [["ssh", "printer", "rm -rf -- /tmp/klipperai-deploy.abc"]]


def test_builder_and_profile_use_current_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy.shutil, "which", lambda _: "uv")

    def execute(command, **kwargs):
        assert command[:3] == ["uv", "build", "--wheel"]
        assert kwargs["cwd"] == deploy.ROOT
        wheel_file(tmp_path)

    monkeypatch.setattr(deploy, "run", execute)
    assert deploy.build_wheel(tmp_path).is_file()
    monkeypatch.setattr(deploy, "ROOT", tmp_path)
    (tmp_path / ".local").mkdir()
    (tmp_path / ".local/deploy-targets.json").write_text(
        json.dumps({"test": {"host": "printer", "install_dir": "/home/pi/KlipperAI"}})
    )
    monkeypatch.setattr(deploy.sys, "argv", ["deploy", "test", "--dry-run"])
    received = []
    monkeypatch.setattr(deploy, "deploy", lambda *a, **k: received.append((a, k)))
    deploy.main()
    assert received[0][0][:2] == ("printer", "/home/pi/KlipperAI")
    assert received[0][1]["dry_run"] is True


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/readyz",
        "http://example.com/readyz",
        "http://localhost/healthz",
        "http://key@localhost/readyz",
    ],
)
def test_remote_cli_rejects_nonlocal_probe_before_service_actions(monkeypatch, url):
    monkeypatch.setattr(
        update.sys,
        "argv",
        ["update", "--install-dir", "/home/pi/KlipperAI", "--rollback", "--url", url],
    )
    with pytest.raises(SystemExit) as result:
        update.main()
    assert result.value.code == 2
