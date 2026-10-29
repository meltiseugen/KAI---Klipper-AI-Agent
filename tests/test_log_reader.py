"""Real-file coverage of the log reader's read-only and bounded I/O contract."""

import gzip
import os
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

import klipperai_agent.infrastructure.host.log_reader as module
from klipperai_agent.domain.logs import LogReadError
from klipperai_agent.infrastructure.host.log_reader import ReadOnlyLogReader


def test_inventory_is_bounded_respects_exclusions_and_ignores_nonlogs(tmp_path):
    for name in (
        "klippy.log",
        "moonraker.log",
        "camera.log",
        "camera.log.1",
        "camera.log.2.gz",
        "secret.cfg",
        "bad name.log",
    ):
        (tmp_path / name).write_text("data\n")
    (tmp_path / "directory.log").mkdir()
    for index in range(24):
        (tmp_path / f"extra-{index}.log").write_text("other\n")
    inventory = ReadOnlyLogReader(tmp_path, ("camera.log",)).inventory()
    assert len(inventory.files) == 16 and inventory.truncated
    assert {"klippy.log", "moonraker.log"} <= {item.name for item in inventory.files}
    assert all(
        not item.name.startswith("camera") and item.name != "secret.cfg" for item in inventory.files
    )
    assert any("other files omitted" in note for note in inventory.notes)
    assert ReadOnlyLogReader(tmp_path / "missing").inventory().notes
    assert not ReadOnlyLogReader(tmp_path, ("*",)).inventory().files


def test_reads_only_listed_identity_and_does_not_follow_redirects_or_truncation(
    tmp_path, monkeypatch
):
    path = tmp_path / "klippy.log"
    path.write_text("one\napi_key=private-test-key\nMCU fault\n")
    before = path.read_bytes()
    reader = ReadOnlyLogReader(tmp_path)
    reference = reader.inventory().files[0]
    original = os.open
    flags_seen = []

    def read_only_open(path, flags, *args, **kwargs):
        flags_seen.append(flags)
        assert not flags & (os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC)
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", read_only_open)
    window = reader.read_window(reference)
    assert "private-test-key" not in window.content and "[REDACTED]" in window.content
    assert window.start_byte == 0 and window.next_before_byte is None
    assert not window.partial and flags_seen and path.read_bytes() == before
    with pytest.raises(LogReadError, match="inventory"):
        reader.read_window(replace(reference, name="../outside.log"))
    with pytest.raises(LogReadError, match="rotated"):
        reader.read_window(replace(reference, inode=reference.inode + 1))
    with pytest.raises(LogReadError, match="cursor"):
        reader.read_window(reference, reference.size_bytes + 1)
    with pytest.raises(LogReadError, match="cursor"):
        reader.read_window(reference, -1)
    path.write_text("x")
    with pytest.raises(LogReadError, match="truncated"):
        reader.read_window(reference)
    path.unlink()
    with pytest.raises(LogReadError, match="could not"):
        reader.read_window(reference)


def test_appends_are_excluded_and_older_cursors_cover_boundary_records(tmp_path):
    path = tmp_path / "klippy.log"
    content = "".join(f"record {index}: evidence\n" for index in range(30000))
    path.write_text(content)
    reader = ReadOnlyLogReader(tmp_path)
    reference = reader.inventory().files[0]
    with path.open("a") as target:
        target.write("APPENDED AFTER INVENTORY\n")
    newest = reader.read_window(reference)
    assert newest.partial and "APPENDED" not in newest.content
    assert newest.next_before_byte and newest.start_byte > 0
    older = reader.read_window(reference, newest.next_before_byte)
    assert older.end_byte == newest.start_byte
    assert older.content.splitlines()[-1] in content
    assert older.content.splitlines()[-1] != newest.content.splitlines()[0]
    empty = reader.read_window(reference, 0)
    assert empty.content == "" and empty.partial
    # Unterminated oversized records cannot be mistaken for complete log lines.
    path.write_bytes(b"x" * (module.WINDOW_BYTES * 2))
    window = reader.read_window(reader.inventory().files[0])
    assert not window.content and window.next_before_byte == module.WINDOW_BYTES


def test_compressed_logs_have_bounded_input_output_and_no_random_byte_seek(tmp_path):
    path = tmp_path / "klippy.log.1.gz"
    text = b"previous event\n" * 30000 + b"MCU fault\n"
    path.write_bytes(gzip.compress(text))
    original = path.read_bytes()
    reader = ReadOnlyLogReader(tmp_path)
    reference = reader.inventory().files[0]
    assert reference.compressed and reference.rotated
    window = reader.read_window(reference)
    assert "MCU fault" in window.content and window.partial
    assert window.next_before_byte is None and path.read_bytes() == original
    with pytest.raises(LogReadError, match="final window"):
        reader.read_window(reference, 1)
    with path.open("ab") as handle:
        handle.write(gzip.compress(b"APPENDED\n"))
    with pytest.raises(LogReadError, match="changed"):
        reader.read_window(reference)
    with pytest.raises(LogReadError, match="input"):
        reader._compressed(BytesIO(), module.INFLATE_BYTES + 1)
    path.write_bytes(gzip.compress(b"x" * (module.INFLATE_BYTES + 1)))
    with pytest.raises(LogReadError, match="decompression"):
        reader.read_window(reader.inventory().files[0])
    path.write_bytes(b"not a gzip file")
    with pytest.raises(LogReadError, match="could not"):
        reader.read_window(reader.inventory().files[0])


def test_symlinks_and_replaced_special_files_are_refused(tmp_path, monkeypatch):
    path = tmp_path / "klippy.log"
    path.write_text("unchanged\n")
    reader = ReadOnlyLogReader(tmp_path)
    reference = reader.inventory().files[0]
    original_link_check = Path.is_symlink
    monkeypatch.setattr(
        Path, "is_symlink", lambda value: value == path or original_link_check(value)
    )
    with pytest.raises(LogReadError, match="Redirected"):
        reader.read_window(reference)
    monkeypatch.setattr(Path, "is_symlink", original_link_check)
    monkeypatch.setattr(module.os, "fstat", lambda _: SimpleNamespace(st_mode=0))
    with pytest.raises(LogReadError, match="rotated"):
        reader.read_window(reference)


def test_disappearing_inventory_entry_is_a_gap(tmp_path, monkeypatch):
    original_stat = Path.stat

    def disappeared(path, *args, **kwargs):
        if path.name == "klippy.log":
            raise FileNotFoundError
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", disappeared)

    class Disappearing:
        name = "klippy.log"

        def is_symlink(self):
            return False

        def stat(self, **kwargs):
            raise FileNotFoundError

    class Linked(Disappearing):
        def is_symlink(self):
            return True

    class Entries:
        def __enter__(self):
            return iter([Disappearing(), Linked()])

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(module.os, "scandir", lambda _: Entries())
    result = ReadOnlyLogReader(tmp_path).inventory()
    assert not result.files and any("disappeared" in note for note in result.notes)


@pytest.mark.skipif(
    os.name == "nt", reason="Native Unix symlink/FIFO checks run on printer-host platforms"
)
def test_native_symlinks_fifos_and_hardlinks_are_never_exposed(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    secret = tmp_path / "private.txt"
    secret.write_text("private data")
    (logs / "symlink.log").symlink_to(secret)
    os.mkfifo(logs / "fifo.log")
    os.link(secret, logs / "hardlink.log")
    reader = ReadOnlyLogReader(logs)
    assert reader.inventory().files == []
    current = logs / "klippy.log"
    current.write_text("public log\n")
    reference = reader.inventory().files[0]
    os.link(current, tmp_path / "second-name")
    with pytest.raises(LogReadError):
        reader.read_window(reference)


def test_hardlinks_are_rejected_on_all_supported_platforms(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    path = logs / "klippy.log"
    path.write_text("public evidence\n")
    reader = ReadOnlyLogReader(logs)
    reference = reader.inventory().files[0]
    os.link(path, tmp_path / "second-link")
    assert reader.inventory().files == []
    with pytest.raises(LogReadError):
        reader.read_window(reference)
