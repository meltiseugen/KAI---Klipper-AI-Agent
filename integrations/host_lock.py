"""Process locks shared by the administrative integration helpers."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

WINDOWS = os.name == "nt"


class MaintenanceBusy(RuntimeError):
    pass


@contextmanager
def locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never unlink: simultaneous processes must keep locking the same inode.
    with path.open("a+b") as stream:
        try:
            if WINDOWS:
                import msvcrt

                if not stream.tell():
                    stream.write(b"\0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
        except OSError as exc:
            if isinstance(exc, BlockingIOError) or (WINDOWS and exc.errno == 13):
                raise MaintenanceBusy("Another patch operation is running; retry later.") from exc
            raise
        yield
