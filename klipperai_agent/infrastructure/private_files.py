"""Owner-only application files, rejecting redirected and special files."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import TextIO


def open_private_file(path: Path) -> TextIO:
    if path.is_symlink():
        raise OSError("Application file must not be a symlink.")
    descriptor = os.open(
        path,
        os.O_WRONLY
        | os.O_APPEND
        | os.O_CREAT
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0),
        0o600,
    )
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise OSError("Application file must be regular and must not have hardlinks.")
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        else:
            path.chmod(0o600)
    except BaseException:
        os.close(descriptor)
        raise
    return os.fdopen(descriptor, "a", encoding="utf-8")
