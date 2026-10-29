"""Private SQLite ring: bounded records and a hard 16 MiB database ceiling."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from klipperai_agent.domain.host_history import HostSample
from klipperai_agent.infrastructure.private_files import open_private_file

MAX_DATABASE_BYTES = 16 * 1024 * 1024
MAX_SAMPLE_BYTES = 16384
MAX_PAYLOAD_BYTES = MAX_DATABASE_BYTES // 2


class HostHistoryStore:
    def __init__(self, directory: Path, protected_dirs: tuple[Path, ...], max_samples: int = 1440):
        if not 12 <= max_samples <= 8640:
            raise ValueError("Recorder retention must be between 12 and 8640 samples.")
        self.path = directory.absolute() / "host-history.sqlite3"
        self.protected_dirs = tuple(path.resolve() for path in protected_dirs)
        self.max_samples = max_samples
        self._check_path()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        open_private_file(self.path).close()
        with closing(self._connect()) as db, db:
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute(
                "CREATE TABLE IF NOT EXISTS samples (id INTEGER PRIMARY KEY, stamp REAL, content TEXT)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS sample_stamp ON samples(stamp)")
            self._trim(db, self.max_samples)

    def _check_path(self) -> None:
        paths = [self.path, *(Path(str(self.path) + s) for s in ("-journal", "-wal", "-shm"))]
        if any(parent.is_symlink() for parent in self.path.parents) or any(
            path.is_symlink()
            or (path.exists() and (not path.is_file() or path.stat().st_nlink != 1))
            or any(path.resolve().is_relative_to(root) for root in self.protected_dirs)
            for path in paths
        ):
            raise ValueError("Host history must be private and outside printer files.")

    def _connect(self) -> sqlite3.Connection:
        self._check_path()
        if self.path.stat().st_size > MAX_DATABASE_BYTES:
            raise ValueError("Host history database exceeds its byte bound.")
        db = sqlite3.connect(self.path, timeout=1)
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
        db.execute(f"PRAGMA max_page_count={MAX_DATABASE_BYTES // page_size}")
        db.execute("PRAGMA secure_delete=ON")
        return db

    @staticmethod
    def _trim(db: sqlite3.Connection, keep: int) -> None:
        db.execute(
            "DELETE FROM samples WHERE id NOT IN (SELECT id FROM samples ORDER BY id DESC LIMIT ?)",
            (keep,),
        )

    def append(self, sample: HostSample) -> None:
        content = sample.json(ensure_ascii=True)
        if len(content.encode("utf-8")) > MAX_SAMPLE_BYTES:
            raise ValueError("Host sample exceeded its storage bound.")
        with closing(self._connect()) as db, db:
            self._trim(db, self.max_samples - 1)
            # Leave room for indexes, page fragmentation and the next sample.
            size = db.execute("SELECT COALESCE(SUM(length(content)), 0) FROM samples").fetchone()[0]
            while size + len(content) > MAX_PAYLOAD_BYTES:
                db.execute("DELETE FROM samples WHERE id=(SELECT MIN(id) FROM samples)")
                size = db.execute(
                    "SELECT COALESCE(SUM(length(content)), 0) FROM samples"
                ).fetchone()[0]
            db.execute(
                "INSERT INTO samples(stamp, content) VALUES (?, ?)", (sample.unix_time, content)
            )

    def window(self, stamp: float) -> list[HostSample]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT content FROM samples WHERE stamp BETWEEN ? AND ? ORDER BY id DESC LIMIT 128",
                (stamp - 90, stamp + 10),
            ).fetchall()
        return sorted(
            (HostSample.parse_raw(row[0]) for row in rows), key=lambda item: item.unix_time
        )
