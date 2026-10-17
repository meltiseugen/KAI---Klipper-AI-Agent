"""Bounded reads of current/recent Klippy logs, including common rotations."""

from __future__ import annotations

import gzip
import os
import re
import stat
import zlib
from fnmatch import fnmatch
from pathlib import Path

from klipperai_agent.domain.redaction import redact_text
from klipperai_agent.domain.shutdown import LogExcerpt, ShutdownLogs

TAIL_BYTES = 2 * 1024 * 1024
INFLATE_BYTES = 16 * 1024 * 1024
_NAME = re.compile(r"klippy\.log(?:\.[0-9][0-9_.-]*)?(?:\.gz)?$")


def _read(path: Path) -> LogExcerpt:
    with path.open("rb") as raw:
        if not stat.S_ISREG(os.fstat(raw.fileno()).st_mode):
            raise OSError("Not a regular log")
        if path.suffix == ".gz":
            if os.fstat(raw.fileno()).st_size > INFLATE_BYTES:
                raise OSError("Compressed input exceeds read budget")
            with gzip.GzipFile(fileobj=raw) as compressed:
                data = bytearray()
                consumed = 0
                while chunk := compressed.read(min(65536, INFLATE_BYTES + 1 - consumed)):
                    consumed += len(chunk)
                    if consumed > INFLATE_BYTES:
                        raise OSError("Compressed log exceeds read budget")
                    data.extend(chunk)
                    if len(data) > TAIL_BYTES:
                        del data[:-TAIL_BYTES]
                partial = consumed > TAIL_BYTES
                body = bytes(data)
        else:
            raw.seek(0, 2)
            size = raw.tell()
            partial = size > TAIL_BYTES
            raw.seek(max(0, size - TAIL_BYTES))
            body = raw.read(TAIL_BYTES)
    if partial:
        # Never parse a partial first line as an intact record.
        body = body.partition(b"\n")[2]
    return LogExcerpt(path.name, redact_text(body.decode("utf-8", errors="replace")), partial)


def collect_shutdown_logs(directory: Path, excluded: tuple[str, ...]) -> ShutdownLogs:
    result = ShutdownLogs()
    excludes = tuple(item.strip().lower() for item in excluded)
    if any(fnmatch("klippy.log", item) or fnmatch("klippy", item) for item in excludes):
        result.notes.append("Klippy host log collection is excluded, including rotations.")
        return result
    try:
        candidates = []
        for path in directory.iterdir():
            if not _NAME.fullmatch(path.name) or path.is_symlink():
                continue
            if any(fnmatch(path.name.lower(), item) for item in excludes):
                continue
            if path.resolve().parent != directory.resolve() or not path.is_file():
                continue
            candidates.append((path.name == "klippy.log", path.stat().st_mtime, path))
        candidates.sort(key=lambda entry: entry[:2], reverse=True)
    except OSError:
        result.notes.append("Klippy log directory unavailable or unreadable.")
        return result
    if not candidates:
        result.notes.append("No eligible Klippy logs found.")
    if len(candidates) > 3:
        result.notes.append(
            "Only current/recent three log files searched; older rotations omitted."
        )
    for _, _, path in candidates[:3]:
        try:
            excerpt = _read(path)
        except (OSError, EOFError, zlib.error):
            result.notes.append(
                f"{path.name}: unreadable, corrupt, or exceeds decompression budget."
            )
            continue
        result.excerpts.append(excerpt)
        if excerpt.partial:
            result.notes.append(
                f"{path.name}: only final {TAIL_BYTES} bytes searched; earlier events/clock anchors may be missing."
            )
    return result
