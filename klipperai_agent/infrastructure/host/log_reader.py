"""Bounded reads of named printer logs; no commands, writes or model-selected paths."""

from __future__ import annotations

import gzip
import hashlib
import os
import re
import stat
import zlib
from datetime import datetime, timezone
from fnmatch import fnmatch
from heapq import nlargest
from pathlib import Path

from klipperai_agent.domain.logs import (
    LOG_INFLATE_BYTES as INFLATE_BYTES,
)
from klipperai_agent.domain.logs import (
    LOG_WINDOW_BYTES as WINDOW_BYTES,
)
from klipperai_agent.domain.logs import (
    LogFile,
    LogInventory,
    LogReadError,
    LogWindow,
)
from klipperai_agent.domain.redaction import redact_text

INVENTORY_FILES = 16
_LOG_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.log(?:\.[0-9][A-Za-z0-9_.-]*)?(?:\.gz)?$")


def _stamp(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


class ReadOnlyLogReader:
    def __init__(self, directory: Path, excluded: tuple[str, ...] = ()):
        self.directory = directory.resolve()
        self.excluded = tuple(item.strip().lower() for item in excluded)

    def _eligible(self, name: str) -> bool:
        if len(name) > 160 or not _LOG_NAME.fullmatch(name):
            return False
        lowered = name.lower()
        base = lowered.split(".log", 1)[0]
        return not any(
            fnmatch(candidate, pattern)
            for pattern in self.excluded
            for candidate in (lowered, base, base + ".log")
        )

    def inventory(self) -> LogInventory:
        result = LogInventory()
        count = 0

        def candidates():
            nonlocal count
            with os.scandir(self.directory) as entries:
                for entry in entries:
                    if not self._eligible(entry.name) or entry.is_symlink():
                        continue
                    try:
                        # Path.stat supplies real file identity on Windows too;
                        # recent Python DirEntry.stat reports zero device/inode there.
                        info = (self.directory / entry.name).stat(follow_symlinks=False)
                    except OSError:
                        result.notes.append("A log disappeared or could not be inspected.")
                        continue
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        continue
                    count += 1
                    identity = f"{entry.name}:{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}"
                    yield LogFile(
                        hashlib.sha256(identity.encode()).hexdigest()[:24],
                        entry.name,
                        info.st_size,
                        _stamp(info.st_mtime),
                        info.st_dev,
                        info.st_ino,
                        entry.name.endswith(".gz"),
                        not entry.name.endswith(".log"),
                    )

        try:
            result.files = nlargest(
                INVENTORY_FILES,
                candidates(),
                key=lambda item: (
                    not item.rotated
                    and item.name in {"klippy.log", "moonraker.log", "klipperai.log"},
                    not item.rotated,
                    item.modified_at,
                    item.name,
                ),
            )
        except OSError:
            result.notes.append("Configured log directory is unavailable or unreadable.")
        result.truncated = count > INVENTORY_FILES
        if result.truncated:
            result.notes.append(
                f"Only {INVENTORY_FILES} current/recent logs were listed; other files omitted."
            )
        return result

    def read_window(self, reference: LogFile, before_byte: int | None = None) -> LogWindow:
        if not self._eligible(reference.name):
            raise LogReadError("Log is outside the permitted log inventory.")
        path = self.directory / reference.name
        try:
            if path.is_symlink() or path.resolve().parent != self.directory:
                raise LogReadError("Redirected log paths are not permitted.")
            # O_NONBLOCK prevents a substituted FIFO from blocking before fstat.
            flags = (
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0)
                | getattr(os, "O_BINARY", 0)
            )
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb") as handle:
                info = os.fstat(handle.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or (info.st_dev, info.st_ino) != (reference.device, reference.inode)
                    or info.st_size < reference.size_bytes
                ):
                    raise LogReadError("Log rotated or was truncated. Refresh the log inventory.")
                if reference.compressed:
                    if info.st_size != reference.size_bytes:
                        raise LogReadError("Compressed log changed. Refresh the log inventory.")
                    if before_byte is not None:
                        raise LogReadError("Compressed logs support only a bounded final window.")
                    body, end = self._compressed(handle, info.st_size)
                    start = max(0, end - len(body))
                else:
                    end = reference.size_bytes if before_byte is None else before_byte
                    if not 0 <= end <= reference.size_bytes:
                        raise LogReadError("Byte cursor is outside the listed log snapshot.")
                    start = max(0, end - WINDOW_BYTES)
                    handle.seek(start)
                    body = handle.read(end - start)
        except (OSError, EOFError, zlib.error) as exc:
            raise LogReadError("Log could not be read within its bounded read budget.") from exc
        original_start = start
        if start:
            prefix, separator, body = body.partition(b"\n")
            start += len(prefix) + len(separator)
        content = redact_text(body.decode("utf-8", errors="replace"))
        digest = hashlib.sha256(content.encode()).hexdigest()
        identity = f"{reference.id}:{start}:{end}:{digest}"
        return LogWindow(
            hashlib.sha256(identity.encode()).hexdigest()[:24],
            reference.id,
            reference.name,
            content,
            datetime.now(timezone.utc).isoformat(),
            digest,
            start,
            end,
            (start if start < end else original_start)
            if original_start and not reference.compressed
            else None,
            original_start > 0 or (not reference.compressed and end < info.st_size),
            reference.compressed,
        )

    @staticmethod
    def _compressed(handle, size: int) -> tuple[bytes, int]:
        if size > INFLATE_BYTES:
            raise LogReadError("Compressed log input exceeds the read budget.")
        data = bytearray()
        consumed = 0
        with gzip.GzipFile(fileobj=handle) as source:
            while chunk := source.read(min(65536, INFLATE_BYTES + 1 - consumed)):
                consumed += len(chunk)
                if consumed > INFLATE_BYTES:
                    raise LogReadError("Compressed log exceeds the decompression budget.")
                data.extend(chunk)
                if len(data) > WINDOW_BYTES:
                    del data[:-WINDOW_BYTES]
        return bytes(data), consumed
