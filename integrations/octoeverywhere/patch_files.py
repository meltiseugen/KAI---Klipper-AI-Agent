"""Inspect both OE files, back them up and replace each atomically under the shared lock."""

from __future__ import annotations

import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from maintenance_state import MaintenanceState
from route_patch import RoutePatch


@dataclass(frozen=True)
class FileChange:
    path: Path
    original: bytes
    desired: bytes
    metadata: os.stat_result

    def unchanged(self) -> bool:
        current = self.path.lstat()
        return (current.st_ino, current.st_size, current.st_mtime_ns, current.st_mode) == (
            self.metadata.st_ino,
            self.metadata.st_size,
            self.metadata.st_mtime_ns,
            self.metadata.st_mode,
        ) and self.path.read_bytes() == self.original


@dataclass(frozen=True)
class PatchPlan:
    files: tuple[FileChange, ...]
    status: str

    @property
    def changes(self) -> tuple[FileChange, ...]:
        return tuple(item for item in self.files if item.original != item.desired)


class PatchFiles:
    def __init__(self, root: Path, patch: RoutePatch, state: MaintenanceState):
        self.root, self.patch, self.state = root, patch, state
        self.paths = (
            root / "moonraker_octoeverywhere/moonrakerapirouter.py",
            root / "moonraker_octoeverywhere/static/oe-ui.js",
        )

    def git_busy(self) -> bool:
        git = self.root / ".git"
        if git.is_file():
            text = git.read_text(encoding="utf-8").strip()
            if not text.startswith("gitdir: "):
                raise ValueError("Unrecognized .git file; checkout unchanged")
            git = self.root / text.removeprefix("gitdir: ")
        return any(
            (git / name).exists()
            for name in (
                "index.lock",
                "HEAD.lock",
                "packed-refs.lock",
                "rebase-apply",
                "rebase-merge",
                "MERGE_HEAD",
            )
        )

    def plan(self, restore: bool = False) -> PatchPlan:
        metadata = [path.lstat() for path in self.paths]
        if any(not stat.S_ISREG(item.st_mode) or item.st_nlink != 1 for item in metadata):
            raise ValueError("OE patch targets must be regular files without symlinks or hardlinks")
        originals = [path.read_bytes() for path in self.paths]
        texts = tuple(data.decode("utf-8").replace("\r\n", "\n") for data in originals)
        clean = self.patch.remove(*texts)
        desired = clean if restore else self.patch.apply(*texts)
        # Preserve byte-for-byte contents when there is no semantic change, including CRLF.
        files = tuple(
            FileChange(path, original, original if text == output else output.encode("utf-8"), info)
            for path, original, text, output, info in zip(
                self.paths, originals, texts, desired, metadata
            )
        )
        status = "current" if texts == desired else "absent" if texts == clean else "outdated"
        return PatchPlan(files, status)

    @staticmethod
    def stage(item: FileChange, data: bytes) -> Path:
        fd, name = tempfile.mkstemp(prefix=".klipperai-", dir=item.path.parent)
        path = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(path, stat.S_IMODE(item.metadata.st_mode))
            if hasattr(os, "chown"):
                os.chown(path, item.metadata.st_uid, item.metadata.st_gid)
            return path
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def commit(self, plan: PatchPlan) -> bool:
        if not plan.changes:
            return False
        staged: dict[Path, Path] = {}
        committed: list[FileChange] = []
        try:
            for item in plan.changes:
                staged[item.path] = self.stage(item, item.desired)
            self.verify(plan)
            backup_root = self.state.path("backups")
            backup_root.mkdir(parents=True, exist_ok=True)
            backup = Path(tempfile.mkdtemp(prefix="change-", dir=backup_root))
            for item in plan.files:
                (backup / item.path.name).write_bytes(item.original)
            print(f"[KlipperAI OE] Backup: {backup}")
            self.state.mark("restart-pending")
            self.verify(plan)
            for item in plan.changes:
                os.replace(staged[item.path], item.path)
                committed.append(item)
            return True
        except BaseException:
            for item in reversed(committed):
                # Never roll back a concurrent external writer's data.
                if item.path.read_bytes() == item.desired:
                    rollback = self.stage(item, item.original)
                    try:
                        os.replace(rollback, item.path)
                    finally:
                        rollback.unlink(missing_ok=True)
            raise
        finally:
            for path in staged.values():
                path.unlink(missing_ok=True)

    def verify(self, plan: PatchPlan) -> None:
        if self.git_busy() or not all(item.unchanged() for item in plan.files):
            raise RuntimeError("Checkout changed during patch preparation; retry after the update")
