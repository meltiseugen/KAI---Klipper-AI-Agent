"""Private host storage for provider credentials, preferences and usage counters."""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from klipperai_agent.domain.provider_settings import (
    ProviderConflict,
    ProviderLimitError,
    ProviderPolicy,
)
from klipperai_agent.infrastructure.private_files import open_private_file


class ProviderStore:
    def __init__(self, directory: Path, protected_dirs: tuple[Path, ...]):
        self.path = directory.absolute() / "providers.sqlite3"
        self.protected_dirs = tuple(root.resolve() for root in protected_dirs)
        self._check_path()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        open_private_file(self.path).close()
        with closing(self._connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY CHECK (id=1), revision INTEGER NOT NULL,
                    policy TEXT NOT NULL, api_key TEXT
                );
                CREATE TABLE IF NOT EXISTS usage (
                    day TEXT PRIMARY KEY, requests INTEGER NOT NULL, tokens INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS calls (at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS cooldown (id INTEGER PRIMARY KEY, until REAL NOT NULL);
            """)

    def _check_path(self) -> None:
        paths = [self.path, *(Path(str(self.path) + s) for s in ("-journal", "-wal", "-shm"))]
        if any(parent.is_symlink() for parent in self.path.parents) or any(
            path.is_symlink()
            or (path.exists() and (not path.is_file() or path.stat().st_nlink != 1))
            or any(path.resolve().is_relative_to(root) for root in self.protected_dirs)
            for path in paths
        ):
            raise ValueError(
                "Provider storage must be private and outside the checkout and printer files."
            )

    def _connect(self) -> sqlite3.Connection:
        self._check_path()
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA secure_delete=ON")
        return db

    def load(self) -> tuple[int, ProviderPolicy | None, str | None]:
        with closing(self._connect()) as db:
            row = db.execute("SELECT revision, policy, api_key FROM settings WHERE id=1").fetchone()
        return (int(row[0]), ProviderPolicy.parse_raw(row[1]), row[2]) if row else (0, None, None)

    def save(self, revision: int, policy: ProviderPolicy, key: str | None) -> int:
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT revision FROM settings WHERE id=1").fetchone()
            if (row[0] if row else 0) != revision:
                raise ProviderConflict("Provider settings changed. Reload settings before saving.")
            db.execute(
                "INSERT OR REPLACE INTO settings VALUES (1, ?, ?, ?)",
                (revision + 1, policy.json(), key),
            )
        return revision + 1

    def reserve(self, policy: ProviderPolicy, tokens: int) -> tuple[str, int]:
        now = time.time()
        day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM calls WHERE at <= ?", (now - 60,))
            db.execute("DELETE FROM usage WHERE day < ?", (day,))
            wait = db.execute("SELECT until FROM cooldown WHERE id=1").fetchone()
            if wait and wait[0] > now:
                raise ProviderLimitError("Provider cooldown is active. Try again later.")
            rpm = db.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
            row = db.execute("SELECT requests, tokens FROM usage WHERE day=?", (day,)).fetchone()
            requests, used = row or (0, 0)
            if rpm >= policy.requests_per_minute:
                raise ProviderLimitError("Provider request limit per minute reached.")
            if requests >= policy.requests_per_day or used + tokens > policy.tokens_per_day:
                raise ProviderLimitError(
                    "Daily provider usage limit reached. Resets at midnight UTC."
                )
            db.execute("INSERT INTO calls VALUES (?)", (now,))
            db.execute(
                "INSERT OR REPLACE INTO usage VALUES (?, ?, ?)", (day, requests + 1, used + tokens)
            )
        return day, tokens

    def settle(self, reservation: tuple[str, int], actual: int) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE usage SET tokens = MAX(0, tokens + ?) WHERE day=?",
                (actual - reservation[1], reservation[0]),
            )

    def cooldown(self, seconds: float) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT INTO cooldown VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET until=MAX(until, excluded.until)",
                (time.time() + seconds,),
            )

    def usage(self) -> dict[str, int | str]:
        day = datetime.now(timezone.utc).date().isoformat()
        with closing(self._connect()) as db:
            row = db.execute("SELECT requests, tokens FROM usage WHERE day=?", (day,)).fetchone()
        requests, tokens = row or (0, 0)
        return {"day_utc": day, "requests": requests, "tokens": tokens}
