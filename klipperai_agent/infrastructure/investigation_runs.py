"""Leased public checkpoints; a completion and its checkpoint removal commit together."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Callable

from klipperai_agent.domain.investigation import (
    Evidence,
    Investigation,
    PendingInvestigation,
    utc_now,
)
from klipperai_agent.domain.redaction import redact_data
from klipperai_agent.domain.repositories import InvestigationConflict
from klipperai_agent.infrastructure.investigation_records import ensure_revision


def lease_deadline() -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()


class SqliteRunRepository:
    def __init__(self, connect: Callable[[], sqlite3.Connection], retention_days: int):
        self._connect = connect
        self._retention_days = retention_days
        with closing(connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS pending_runs (
                investigation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, content TEXT NOT NULL,
                owner TEXT NOT NULL, lease_until TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY (investigation_id) REFERENCES investigations(id) ON DELETE CASCADE
            )""")

    def begin(self, investigation: Investigation, run: PendingInvestigation, owner: str) -> None:
        run = PendingInvestigation.parse_obj(redact_data(run.model_dump()))
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            cutoff = (datetime.now(timezone.utc) - timedelta(days=self._retention_days)).isoformat()
            db.execute("DELETE FROM investigations WHERE updated_at < ?", (cutoff,))
            ensure_revision(db, investigation)
            if db.execute(
                "SELECT 1 FROM pending_runs WHERE investigation_id=?", (investigation.id,)
            ).fetchone():
                raise InvestigationConflict(
                    "This investigation is still running or awaiting recovery."
                )
            count = db.execute("SELECT count(*) FROM pending_runs").fetchone()[0]
            if count >= 100:
                raise InvestigationConflict(
                    "Too many unfinished investigations. Delete an unused chat."
                )
            db.execute(
                "INSERT INTO pending_runs VALUES (?, ?, ?, ?, ?, ?)",
                (investigation.id, run.id, run.json(), owner, lease_deadline(), run.created_at),
            )
            db.execute(
                "UPDATE investigations SET updated_at=? WHERE id=?", (utc_now(), investigation.id)
            )

    def claim(self, printer_id: str, owner: str, before: str) -> str | None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self._retention_days)).isoformat()
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT p.* FROM pending_runs p JOIN investigations i ON i.id=p.investigation_id
                WHERE i.printer_id=? AND i.updated_at>=? AND p.lease_until<=?
                AND p.created_at<=? ORDER BY i.updated_at LIMIT 1""",
                (printer_id, cutoff, utc_now(), before),
            ).fetchone()
            if row is None:
                return None
            run = PendingInvestigation.parse_raw(row["content"])
            run.attempts += 1
            db.execute(
                "UPDATE pending_runs SET content=?, owner=?, lease_until=? WHERE investigation_id=?",
                (run.json(), owner, lease_deadline(), row["investigation_id"]),
            )
            return str(row["investigation_id"])

    def checkpoint(
        self,
        printer_id: str,
        thread_id: str,
        run_id: str,
        owner: str,
        evidence: list[Evidence] | None = None,
    ) -> None:
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if evidence is None:
                changed = db.execute(
                    """UPDATE pending_runs SET lease_until=?
                    WHERE investigation_id=? AND run_id=? AND owner=? AND investigation_id IN
                    (SELECT id FROM investigations WHERE printer_id=?)""",
                    (lease_deadline(), thread_id, run_id, owner, printer_id),
                ).rowcount
                if not changed:
                    raise InvestigationConflict(
                        "The investigation was deleted or recovered by another worker."
                    )
                return
            row = db.execute(
                """SELECT p.content FROM pending_runs p JOIN investigations i ON i.id=p.investigation_id
                WHERE i.printer_id=? AND i.id=? AND p.run_id=? AND p.owner=?""",
                (printer_id, thread_id, run_id, owner),
            ).fetchone()
            if row is None:
                raise InvestigationConflict(
                    "The investigation was deleted or recovered by another worker."
                )
            run = PendingInvestigation.parse_raw(row[0])
            if evidence is not None:
                combined = {item.id: item for item in [*run.evidence, *evidence]}
                run.evidence = [
                    Evidence.parse_obj(redact_data(item.model_dump()))
                    for item in list(combined.values())[-24:]
                ]
            db.execute(
                "UPDATE pending_runs SET content=?, lease_until=? WHERE investigation_id=?",
                (run.json(), lease_deadline(), thread_id),
            )

    def release(self, printer_id: str, owner: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                """UPDATE pending_runs SET lease_until=? WHERE owner=? AND investigation_id IN
                (SELECT id FROM investigations WHERE printer_id=?)""",
                (utc_now(), owner, printer_id),
            )
