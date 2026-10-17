"""Application-owned recovery markers and an OS-released maintenance lock."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from host_lock import MaintenanceBusy, locked  # noqa: E402, F401


class MaintenanceState:
    def __init__(self, directory: Path):
        self.directory = directory

    def path(self, name: str) -> Path:
        return self.directory / f"octoeverywhere-{name}"

    def has(self, name: str) -> bool:
        return self.path(name).exists()

    def mark(self, name: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".oe-state-", dir=self.directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(b"Pending KlipperAI OctoEverywhere maintenance.\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path(name))
        finally:
            Path(temporary).unlink(missing_ok=True)

    def clear(self, name: str) -> None:
        self.path(name).unlink(missing_ok=True)

    def locked(self):
        return locked(self.path("maintenance.lock"))
