from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest


def test_navigation_preserves_other_entries_order_and_unchanged_bytes(mainsail_maintenance):
    module = mainsail_maintenance.navigation
    entry = module.NavigationEntry(icon="M0 0Z")
    other = [{"title": "Other", "href": "/other", "position": 99}, "custom"]
    original = json.dumps(other + [entry.payload()], indent=4).encode()
    assert module.update_navigation(original, entry) is original
    duplicated = json.dumps([entry.payload(), *other, {"title": "KlipperAI"}]).encode()
    assert json.loads(module.update_navigation(duplicated, entry)) == [entry.payload(), *other]
    assert json.loads(module.update_navigation(duplicated, entry, remove=True)) == other
    absent = json.dumps(other).encode()
    assert module.update_navigation(absent, entry, remove=True) is absent
    assert module.update_navigation(None, entry, remove=True) is None
    with pytest.raises(ValueError, match="array"):
        module.update_navigation(b"{}", entry)
    for kwargs in (
        {"title": ""},
        {"href": "javascript:alert(1)"},
        {"href": "//elsewhere"},
        {"href": "/path\n"},
        {"href": "/\\elsewhere"},
        {"target": "iframe"},
        {"position": -1},
        {"position": True},
    ):
        with pytest.raises(ValueError):
            module.NavigationEntry(**kwargs)
    assert module.NavigationEntry(href="https://example.com/assistant").href.startswith("https")


def test_check_install_repair_remove_and_resume(mainsail_maintenance):
    m = mainsail_maintenance
    printer = m.config / "printer.cfg"
    printer.write_bytes(b"[printer]\nkinematics: corexy\n")
    before = printer.read_bytes()
    assert m.cli.main(m.args + ["--check"]) == 1
    assert m.cli.main(m.args + ["--validate"]) == 0
    assert not m.state.exists()
    assert not m.files.theme.exists()
    assert m.cli.main(m.args) == 0
    current = (m.files.path.read_bytes(), m.files.path.stat().st_mtime_ns)
    assert m.cli.main(m.args + ["--check"]) == 0
    assert m.cli.main(m.args + ["--reconcile"]) == 0
    assert (m.files.path.read_bytes(), m.files.path.stat().st_mtime_ns) == current
    assert not (m.state / "backups").exists()
    m.files.path.write_text('[{"title":"Other","href":"/other"}]')
    assert m.cli.main(m.args + ["--reconcile"]) == 0
    assert len(json.loads(m.files.path.read_bytes())) == 2
    assert len(list((m.state / "backups").iterdir())) == 1
    assert m.cli.main(m.args + ["--remove"]) == 0
    removed = m.files.path.read_bytes()
    assert m.cli.main(m.args + ["--reconcile"]) == 0
    assert m.files.path.read_bytes() == removed
    assert m.cli.main(m.args) == 0  # Explicit install resumes repair.
    assert not (m.state / "disabled").exists()
    # Simulate replacing/deleting the whole theme directory during a restore/update.
    m.files.theme.rename(m.config / "previous-theme")
    assert m.cli.main(m.args + ["--reconcile"]) == 0
    assert m.cli.main(m.args + ["--check"]) == 0
    assert printer.read_bytes() == before


def test_invalid_input_and_missing_config_never_overwrite_files(mainsail_maintenance):
    m = mainsail_maintenance
    assert m.cli.main([]) == 1
    assert m.cli.main(m.args + ["--target", "bad"]) == 1
    assert not m.state.exists()
    m.files.theme.mkdir()
    m.files.path.write_bytes(b"{partially edited")
    assert m.cli.main(m.args + ["--reconcile"]) == 1
    assert m.files.path.read_bytes() == b"{partially edited"
    assert not (m.state / "backups").exists()
    m.config.rename(m.config.with_name("missing-config"))
    assert m.cli.main(m.args + ["--reconcile"]) == 1
    assert not m.config.exists()
    with pytest.raises(ValueError, match="does not exist"):
        m.files.prepare(m.navigation.NavigationEntry())


def test_failed_write_and_editor_race_leave_original_or_editor_contents(
    mainsail_maintenance, monkeypatch
):
    m = mainsail_maintenance
    m.files.theme.mkdir()
    m.files.path.write_bytes(b"[]\n")
    original_replace = os.replace
    monkeypatch.setattr(m.io.os, "replace", Mock(side_effect=PermissionError("read only")))
    assert m.cli.main(m.args) == 1
    assert m.files.path.read_bytes() == b"[]\n"
    assert not list(m.files.theme.glob(".klipperai-*"))
    monkeypatch.setattr(m.io.os, "replace", original_replace)
    original_chmod = os.chmod

    def edit_during_staging(path, mode):
        original_chmod(path, mode)
        m.files.path.write_bytes(b'[{"title":"New unrelated entry"}]')

    monkeypatch.setattr(m.io.os, "chmod", edit_during_staging)
    assert m.cli.main(m.args) == 1
    assert m.files.path.read_bytes() == b'[{"title":"New unrelated entry"}]'
    assert not list(m.files.theme.glob(".klipperai-*"))


def test_links_are_refused_and_file_ownership_is_preserved(mainsail_maintenance, monkeypatch):
    m = mainsail_maintenance
    ownership = []
    monkeypatch.setattr(os, "chown", lambda *args: ownership.append(args), raising=False)
    assert m.cli.main(m.args) == 0
    assert ownership and all(
        args[1:] == (m.config.stat().st_uid, m.config.stat().st_gid) for args in ownership
    )
    alias = m.config / "linked-nav"
    os.link(m.files.path, alias)
    assert m.cli.main(m.args) == 1
    alias.unlink()
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == m.files.theme)
    assert m.cli.main(m.args) == 1


def test_manual_and_automatic_navigation_share_a_process_lock(mainsail_maintenance):
    m = mainsail_maintenance
    with m.cli.locked(m.state / "maintenance.lock"):
        assert m.cli.main(m.args) == 1
        assert m.cli.main(m.args + ["--reconcile"]) == 0
    assert m.cli.main(m.args) == 0
