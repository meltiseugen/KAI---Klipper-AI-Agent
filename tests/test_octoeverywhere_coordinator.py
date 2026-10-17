from __future__ import annotations

import io
import json
import subprocess
from unittest.mock import Mock

import pytest


@pytest.fixture
def coordinator(oe_maintenance):
    module = oe_maintenance.updates
    updates = Mock(status=Mock(return_value=module.UpdateStatus(False)))
    service = Mock()
    return module.UpdateCoordinator(oe_maintenance.files, updates, service)


def test_failed_restart_and_refresh_are_retried_without_new_backups(coordinator):
    coordinator.state.mark("reapply.suspended")
    coordinator.service.restart.side_effect = RuntimeError("service unavailable")
    with pytest.raises(RuntimeError, match="service unavailable"):
        coordinator.reconcile()
    assert coordinator.state.has("restart-pending")
    assert coordinator.state.has("reapply.suspended")
    backups = list(coordinator.state.path("backups").iterdir())
    coordinator.service.restart.side_effect = None
    coordinator.reconcile()
    assert not coordinator.state.has("restart-pending")
    assert not coordinator.state.has("reapply.suspended")
    assert list(coordinator.state.path("backups").iterdir()) == backups
    assert coordinator.service.restart.call_count == 2
    coordinator.reconcile()
    assert coordinator.service.restart.call_count == 2

    status = coordinator.updates.status.return_value
    coordinator.updates.status.return_value = type(status)(False, 2)
    coordinator.updates.refresh.side_effect = OSError("Moonraker unavailable")
    with pytest.raises(OSError):
        coordinator.reconcile()
    assert coordinator.state.has("refresh-pending")
    backups = list(coordinator.state.path("backups").iterdir())
    coordinator.updates.refresh.side_effect = None
    coordinator.reconcile()
    assert not coordinator.state.has("refresh-pending")
    assert list(coordinator.state.path("backups").iterdir()) == backups
    assert coordinator.service.restart.call_count == 3
    assert coordinator.state.has("reapply.suspended")


@pytest.mark.parametrize("busy,behind", [(True, 0), (False, 3)])
def test_change_in_update_state_before_writing_defers_everything(
    coordinator, oe_maintenance, busy, behind
):
    original = [path.read_bytes() for path in coordinator.files.paths]
    cls = oe_maintenance.updates.UpdateStatus
    coordinator.updates.status.side_effect = [cls(False), cls(busy, behind)]
    coordinator.reconcile()
    assert [path.read_bytes() for path in coordinator.files.paths] == original
    coordinator.service.restart.assert_not_called()
    assert not coordinator.state.directory.exists()


def test_git_lock_and_upstream_conflict_never_clear_suspension(coordinator):
    coordinator.state.mark("reapply.suspended")
    git = coordinator.files.root / ".git"
    git.mkdir()
    (git / "index.lock").touch()
    coordinator.reconcile()
    coordinator.service.restart.assert_not_called()
    (git / "index.lock").unlink()
    coordinator.files.paths[1].write_text("// upstream changed its initialization\n")
    with pytest.raises(ValueError, match="anchor"):
        coordinator.reconcile()
    assert coordinator.state.has("reapply.suspended")


def test_update_api_and_bounded_service_command(oe_maintenance, monkeypatch):
    module = oe_maintenance.updates
    calls = []
    payload = {"result": {"busy": False, "version_info": {"OE": {"commits_behind_count": 2}}}}

    def fetch(request, timeout):
        calls.append((request, timeout))
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(module.urllib.request, "urlopen", fetch)
    updates = module.MoonrakerUpdates("http://local/", "oe")
    assert updates.status() == module.UpdateStatus(False, 2)
    payload["result"] = {"busy": True}
    assert updates.status().busy
    for value in (
        {},
        {"busy": False, "version_info": {}},
        {"busy": False, "version_info": {"oe": {"commits_behind_count": True}}},
    ):
        payload["result"] = value
        with pytest.raises(ValueError):
            updates.status()
    updates.refresh()
    assert calls[-1][0].method == "POST" and calls[-1][1] == 60
    run = Mock()
    monkeypatch.setattr(module.subprocess, "run", run)
    module.OctoEverywhereService("octoeverywhere").restart()
    assert run.call_args.kwargs == {"check": True, "timeout": 60}
    assert run.call_args.args[0][-1] == "octoeverywhere"


def test_cli_modes_and_failed_restart(oe_maintenance, monkeypatch):
    cli, state, files = oe_maintenance.cli, oe_maintenance.state, oe_maintenance.files
    args = ["--oe-root", str(files.root), "--state-dir", str(state.directory)]
    assert cli.main(args + ["--check"]) == 1
    assert not state.directory.exists()
    assert cli.main(args + ["--validate"]) == 0
    for options in (
        ["--service", "bad;name"],
        ["--moonraker-url", "file:///etc"],
        ["--klipperai-port", "0"],
    ):
        assert cli.main(args + options + ["--validate"]) == 1
    assert cli.main(args) == 0
    assert cli.main(args + ["--check"]) == 0
    failure = Mock(side_effect=subprocess.CalledProcessError(1, "systemctl"))
    monkeypatch.setattr(cli.OctoEverywhereService, "restart", failure)
    assert cli.main(args + ["--restart-service"]) == 1
    failure.side_effect = None
    assert cli.main(args + ["--restart-service"]) == 0
    assert cli.main(args + ["--restore-original", "--restart-service"]) == 0
    assert state.has("reapply.suspended")
    monkeypatch.setattr(
        cli.MoonrakerUpdates, "status", lambda self: oe_maintenance.updates.UpdateStatus(False)
    )
    assert cli.main(args + ["--reconcile"]) == 0
    git = files.root / ".git"
    git.mkdir()
    (git / "index.lock").touch()
    assert cli.main(args) == 1


def test_route_engine_rejects_unbalanced_markers(oe_maintenance):
    patch = oe_maintenance.files.patch
    with pytest.raises(ValueError, match="Incomplete"):
        patch.remove_block("START\n", "START", "END")
    with pytest.raises(ValueError, match="Unrecognized"):
        patch.remove_block("prefix START\nEND\n", "START", "END")
