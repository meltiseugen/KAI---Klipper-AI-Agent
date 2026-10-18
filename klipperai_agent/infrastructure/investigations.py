"""SQLite storage confined to KlipperAI's own data directory."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from klipperai_agent.domain.investigation import (
    Investigation,
    InvestigationTurn,
    PendingInvestigation,
)
from klipperai_agent.domain.redaction import redact_data, redact_text
from klipperai_agent.domain.repositories import (
    ConfirmedMemoryRepository,
    InvestigationConflict,
    RunRepository,
)
from klipperai_agent.infrastructure.confirmed_memory import SqliteConfirmedMemoryRepository
from klipperai_agent.infrastructure.investigation_records import ensure_revision
from klipperai_agent.infrastructure.investigation_runs import SqliteRunRepository
from klipperai_agent.infrastructure.private_files import open_private_file


class SqliteInvestigationRepository:
    def __init__(
        self, data_dir: Path, *, protected_dirs: tuple[Path, ...], retention_days: int = 90
    ):
        self._path = data_dir.resolve() / "investigations.sqlite3"
        self._protected_dirs = tuple(path.resolve() for path in protected_dirs)
        self._retention_days = retention_days
        self._check_path()
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        open_private_file(self._path).close()
        with closing(self._connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS investigations (
                    id TEXT PRIMARY KEY, printer_id TEXT NOT NULL, title TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, revision INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, content TEXT NOT NULL,
                    FOREIGN KEY (investigation_id) REFERENCES investigations(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS investigation_printer ON investigations(printer_id, updated_at);
                CREATE INDEX IF NOT EXISTS turn_investigation ON turns(investigation_id, created_at);
            """)
        self._path.chmod(0o600)
        self.runs: RunRepository = SqliteRunRepository(self._connect, retention_days)
        self.confirmed: ConfirmedMemoryRepository = SqliteConfirmedMemoryRepository(self._connect)

    def _check_path(self) -> None:
        # Reject symlink redirection for the DB and SQLite's auxiliary files.
        paths = [
            self._path,
            *(Path(str(self._path) + suffix) for suffix in ("-journal", "-wal", "-shm")),
        ]
        for path in paths:
            if (
                path.is_symlink()
                or (path.exists() and path.stat().st_nlink > 1)
                or any(path.resolve().is_relative_to(root) for root in self._protected_dirs)
            ):
                raise ValueError(
                    "Investigation storage must stay outside printer configuration, logs and G-code directories."
                )

    def _connect(self) -> sqlite3.Connection:
        self._check_path()
        db = sqlite3.connect(self._path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA secure_delete = ON")
        return db

    def get(self, printer_id: str, investigation_id: str) -> Investigation | None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self._retention_days)).isoformat()
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM investigations WHERE id = ? AND printer_id = ? AND updated_at >= ?",
                (investigation_id, printer_id, cutoff),
            ).fetchone()
            return self._load(db, row) if row else None

    def recent(self, printer_id: str, limit: int = 30) -> list[Investigation]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self._retention_days)).isoformat()
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT * FROM investigations WHERE printer_id = ? AND updated_at >= ? ORDER BY updated_at DESC LIMIT ?",
                (printer_id, cutoff, min(max(limit, 1), 100)),
            ).fetchall()
            return [self._load(db, row, turn_limit=3) for row in rows]

    @staticmethod
    def _load(db: sqlite3.Connection, row: sqlite3.Row, turn_limit: int = 50) -> Investigation:
        turns = db.execute(
            "SELECT content FROM turns WHERE investigation_id = ? ORDER BY rowid DESC LIMIT ?",
            (row["id"], turn_limit),
        ).fetchall()
        pending = db.execute(
            "SELECT content FROM pending_runs WHERE investigation_id=?", (row["id"],)
        ).fetchone()
        return Investigation(
            **{**dict(row), "title": redact_text(row["title"])},
            turns=[
                InvestigationTurn.parse_obj(redact_data(json.loads(item["content"])))
                for item in reversed(turns)
            ],
            pending=PendingInvestigation.parse_obj(redact_data(json.loads(pending[0])))
            if pending
            else None,
        )

    def save_turn(
        self, investigation: Investigation, turn: InvestigationTurn, owner: str | None = None
    ) -> None:
        turn = InvestigationTurn.parse_obj(redact_data(turn.model_dump()))
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            # A deleted in-flight first turn must never recreate the conversation.
            pending = db.execute(
                "SELECT run_id, owner FROM pending_runs WHERE investigation_id=?",
                (investigation.id,),
            ).fetchone()
            if owner is not None:
                if (
                    not pending
                    or not investigation.pending
                    or (pending[0], pending[1]) != (investigation.pending.id, owner)
                ):
                    raise InvestigationConflict(
                        "This investigation was deleted or recovered elsewhere."
                    )
            elif pending:
                raise InvestigationConflict(
                    "Wait for this investigation to finish before rechecking."
                )
            ensure_revision(db, investigation)
            db.execute(
                "UPDATE investigations SET revision = revision + 1, updated_at = ? WHERE id = ? AND printer_id = ? AND revision = ?",
                (
                    turn.created_at,
                    investigation.id,
                    investigation.printer_id,
                    investigation.revision,
                ),
            )
            db.execute(
                "INSERT INTO turns VALUES (?, ?, ?, ?)",
                (turn.id, investigation.id, turn.created_at, turn.json()),
            )
            db.execute("DELETE FROM pending_runs WHERE investigation_id=?", (investigation.id,))
            cutoff = (datetime.now(timezone.utc) - timedelta(days=self._retention_days)).isoformat()
            db.execute(
                "DELETE FROM turns WHERE created_at < ? OR rowid NOT IN (SELECT rowid FROM turns ORDER BY rowid DESC LIMIT 1000)",
                (cutoff,),
            )
            db.execute(
                "DELETE FROM investigations WHERE id NOT IN (SELECT investigation_id FROM turns) AND id NOT IN (SELECT investigation_id FROM pending_runs)"
            )
            db.execute("DELETE FROM investigations WHERE updated_at < ?", (cutoff,))

    def delete(self, printer_id: str, investigation_id: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "DELETE FROM confirmed_memory WHERE printer_id=? AND investigation_id=?",
                (printer_id, investigation_id),
            )
            db.execute(
                "DELETE FROM investigations WHERE id = ? AND printer_id = ?",
                (investigation_id, printer_id),
            )
