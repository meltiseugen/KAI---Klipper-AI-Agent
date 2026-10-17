from __future__ import annotations

import errno
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest


def test_content_checks_repair_partial_and_outdated_patches_without_rewriting_current_files(
    oe_maintenance,
):
    files, state = oe_maintenance.files, oe_maintenance.state
    original = [path.read_bytes() for path in files.paths]
    assert files.plan().status == "absent"
    assert files.commit(files.plan())
    assert state.has("restart-pending")
    before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in files.paths]
    assert files.plan().status == "current"
    assert not files.commit(files.plan())
    assert [(path.read_bytes(), path.stat().st_mtime_ns) for path in files.paths] == before
    # OE updated just the UI file; remaining complete router blocks must still be removed.
    files.paths[1].write_bytes(original[1])
    assert files.plan().status == "outdated"
    assert files.commit(files.plan(restore=True))
    assert [path.read_bytes().replace(b"\r\n", b"\n") for path in files.paths] == [
        data.replace(b"\r\n", b"\n") for data in original
    ]
    assert files.paths[1].read_bytes() == original[1]
    files.commit(files.plan())
    files.patch.port = "8899"
    assert files.plan().status == "outdated"
    files.commit(files.plan())
    assert "127.0.0.1:8899" in files.paths[0].read_text()
    assert len(list(state.path("backups").iterdir())) == 4


def test_write_failure_rolls_back_both_files_and_keeps_backup(oe_maintenance, monkeypatch):
    files = oe_maintenance.files
    plan = files.plan()
    original_replace = os.replace

    def fail_second(source, target):
        if target == files.paths[1]:
            raise PermissionError("read-only target")
        original_replace(source, target)

    monkeypatch.setattr(oe_maintenance.deployment.os, "replace", fail_second)
    with pytest.raises(PermissionError):
        files.commit(plan)
    assert [path.read_bytes() for path in files.paths] == [item.original for item in plan.files]
    assert not list(files.root.rglob(".klipperai-*"))
    backup = next(oe_maintenance.state.path("backups").iterdir())
    assert (backup / files.paths[0].name).read_bytes() == plan.files[0].original


def test_external_changes_are_never_overwritten_during_preparation_or_rollback(
    oe_maintenance, monkeypatch
):
    files = oe_maintenance.files
    plan = files.plan()
    files.paths[0].write_bytes(b"# external update\n")
    with pytest.raises(RuntimeError, match="changed"):
        files.commit(plan)
    assert files.paths[0].read_bytes() == b"# external update\n"
    files.paths[0].write_bytes(plan.files[0].original)
    plan = files.plan()
    original_replace = os.replace

    def race_second(source, target):
        if target == files.paths[1]:
            files.paths[0].write_bytes(b"# another writer\n")
            raise PermissionError("update racing")
        original_replace(source, target)

    monkeypatch.setattr(oe_maintenance.deployment.os, "replace", race_second)
    with pytest.raises(PermissionError):
        files.commit(plan)
    assert files.paths[0].read_bytes() == b"# another writer\n"


def test_staging_cleanup_preserves_mode_and_owner(oe_maintenance, monkeypatch):
    files = oe_maintenance.files
    item = files.plan().files[0]
    ownership = []
    monkeypatch.setattr(os, "chown", lambda *args: ownership.append(args), raising=False)
    staged = files.stage(item, item.desired)
    assert ownership[0][1:] == (item.metadata.st_uid, item.metadata.st_gid)
    assert staged.stat().st_mode == item.metadata.st_mode
    staged.unlink()
    monkeypatch.setattr(os, "chmod", lambda *args: (_ for _ in ()).throw(PermissionError("mode")))
    with pytest.raises(PermissionError):
        files.stage(item, item.desired)
    assert not list(files.root.rglob(".klipperai-*"))


def test_refuses_hardlinks_and_git_operations_in_worktrees(oe_maintenance):
    files = oe_maintenance.files
    alias = files.root / "alias"
    os.link(files.paths[0], alias)
    with pytest.raises(ValueError, match="hardlinks"):
        files.plan()
    alias.unlink()
    git = files.root / "git-data"
    git.mkdir()
    (files.root / ".git").write_text("gitdir: git-data\n")
    (git / "index.lock").touch()
    assert files.git_busy()
    with pytest.raises(RuntimeError, match="changed"):
        files.commit(files.plan())
    (git / "index.lock").unlink()
    assert not files.git_busy()
    (files.root / ".git").write_text("unknown metadata")
    with pytest.raises(ValueError, match="Unrecognized"):
        files.git_busy()


def test_lock_serializes_processes_and_recovers_after_exit(oe_maintenance):
    state, cli = oe_maintenance.state, oe_maintenance.cli
    args = [
        sys.executable,
        cli.__file__,
        "--oe-root",
        str(oe_maintenance.files.root),
        "--state-dir",
        str(state.directory),
    ]
    with state.locked():
        child = subprocess.run(args + ["--reconcile"], capture_output=True, text=True, timeout=10)
        assert child.returncode == 0 and "Another patch operation" in child.stdout
        assert cli.main(args[2:]) == 1
        assert cli.main(args[2:] + ["--reconcile"]) == 0
    with state.locked():
        pass  # No stale-PID cleanup is needed after closing a process-owned lock.
    # Kill a real lock holder: recovery must not depend on a finally block or PID marker.
    script = (
        "import sys; from pathlib import Path; "
        "sys.path.insert(0, sys.argv[1]); "
        "from maintenance_state import MaintenanceState; "
        "state = MaintenanceState(Path(sys.argv[2])); "
        "lock = state.locked(); lock.__enter__(); "
        "print('locked', flush=True); sys.stdin.read()"
    )
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            script,
            str(oe_maintenance.files.patch.templates),
            str(state.directory),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "locked"
        assert cli.main(args[2:]) == 1
    finally:
        child.kill()
        child.communicate(timeout=10)
    with state.locked():
        pass


def test_lock_platform_adapters_distinguish_busy_from_other_errors(oe_maintenance, monkeypatch):
    runtime, state = oe_maintenance.runtime, oe_maintenance.state
    fake = SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=lambda *args: None)
    monkeypatch.setitem(sys.modules, "fcntl", fake)
    monkeypatch.setattr(runtime, "WINDOWS", False)
    with state.locked():
        pass
    fake.flock = lambda *args: (_ for _ in ()).throw(BlockingIOError(errno.EAGAIN, "busy"))
    with pytest.raises(runtime.MaintenanceBusy):
        with state.locked():
            pytest.fail("lock should not be entered")
    fake.flock = lambda *args: (_ for _ in ()).throw(OSError(errno.EIO, "disk"))
    with pytest.raises(OSError, match="disk"):
        with state.locked():
            pytest.fail("lock should not be entered")
    monkeypatch.setattr(runtime, "WINDOWS", True)
    fake_windows = SimpleNamespace(
        LK_NBLCK=1, locking=lambda *args: (_ for _ in ()).throw(OSError(errno.EACCES, "busy"))
    )
    monkeypatch.setitem(sys.modules, "msvcrt", fake_windows)
    with pytest.raises(runtime.MaintenanceBusy):
        with state.locked():
            pytest.fail("lock should not be entered")
