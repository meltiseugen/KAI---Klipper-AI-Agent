"""Snapshot, back up and atomically replace only the custom navigation file."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from typing import Callable

from navigation import NavigationEntry, update_navigation


def snapshot(path: Path) -> tuple[bytes | None, os.stat_result | None]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None, None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError(f"Expected a regular file without symlinks or hardlinks: {path}")
    return path.read_bytes(), info


def same_snapshot(path: Path, before: tuple[bytes | None, os.stat_result | None]) -> bool:
    data, info = snapshot(path)
    original, old = before
    return data == original and (
        info is old
        or (
            info is not None
            and old is not None
            and (info.st_ino, info.st_mtime_ns, info.st_mode, info.st_uid, info.st_gid)
            == (old.st_ino, old.st_mtime_ns, old.st_mode, old.st_uid, old.st_gid)
        )
    )


def atomic_write(
    path: Path,
    data: bytes,
    owner: os.stat_result,
    mode: int = 0o644,
    verify: Callable[[], None] | None = None,
):
    """Stage a complete file in the target directory; never truncate the destination."""
    fd, name = tempfile.mkstemp(prefix=".klipperai-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        if hasattr(os, "chown"):
            os.chown(temporary, owner.st_uid, owner.st_gid)
        if verify:
            verify()
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class NavigationFile:
    def __init__(self, config: Path, state: Path):
        self.config, self.state = config, state
        self.theme = config / ".theme"
        self.path = self.theme / "navi.json"

    def prepare(self, entry: NavigationEntry, remove: bool = False):
        if not self.config.is_dir():
            raise ValueError(f"Printer config directory does not exist: {self.config}")
        if self.theme.is_symlink():
            raise ValueError("Refusing a symlinked .theme directory")
        before = snapshot(self.path)
        return before, update_navigation(before[0], entry, remove)

    def update(self, entry: NavigationEntry, remove: bool = False) -> bool:
        before, desired = self.prepare(entry, remove)
        if desired == before[0]:
            return False
        owner = before[1] or self.config.stat()
        if not self.theme.exists():
            self.theme.mkdir(mode=0o755)
            if hasattr(os, "chown"):
                os.chown(self.theme, owner.st_uid, owner.st_gid)
        if before[0] is not None:
            backups = self.state / "backups"
            backups.mkdir(parents=True, exist_ok=True)
            backup = Path(tempfile.mkdtemp(prefix="change-", dir=backups))
            (backup / "navi.json").write_bytes(before[0])

        def verify():
            if self.theme.is_symlink() or not same_snapshot(self.path, before):
                raise RuntimeError("Navigation changed during maintenance; retry later")

        assert desired is not None
        atomic_write(
            self.path,
            desired,
            owner,
            stat.S_IMODE(before[1].st_mode) if before[1] else 0o644,
            verify,
        )
        return True
