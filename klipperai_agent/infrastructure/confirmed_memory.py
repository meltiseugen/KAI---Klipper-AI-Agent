"""Explicit user statements are retained until forgotten, separately from expiring evidence."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Callable

from klipperai_agent.domain.investigation import ConfirmedMemory
from klipperai_agent.domain.redaction import redact_data
from klipperai_agent.domain.repositories import InvestigationConflict


class SqliteConfirmedMemoryRepository:
    def __init__(self, connect: Callable[[], sqlite3.Connection]):
        self._connect = connect
        with closing(connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS confirmed_memory (
                id TEXT PRIMARY KEY, printer_id TEXT NOT NULL, investigation_id TEXT,
                content TEXT NOT NULL
            )""")

    def list(self, printer_id: str) -> list[ConfirmedMemory]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT content FROM confirmed_memory WHERE printer_id=? ORDER BY rowid DESC",
                (printer_id,),
            ).fetchall()
        return [
            ConfirmedMemory.parse_obj(redact_data(ConfirmedMemory.parse_raw(row[0]).model_dump()))
            for row in rows
        ]

    def save(self, printer_id: str, memory: ConfirmedMemory) -> None:
        memory = ConfirmedMemory.parse_obj(redact_data(memory.model_dump()))
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if (
                memory.investigation_id
                and not db.execute(
                    "SELECT 1 FROM investigations WHERE id=? AND printer_id=?",
                    (memory.investigation_id, printer_id),
                ).fetchone()
            ):
                raise InvestigationConflict("The source investigation was deleted. Reload memory.")
            if (
                db.execute(
                    "SELECT count(*) FROM confirmed_memory WHERE printer_id=?", (printer_id,)
                ).fetchone()[0]
                >= 100
            ):
                raise InvestigationConflict(
                    "Memory is full. Forget an outdated entry before adding another."
                )
            db.execute(
                "INSERT INTO confirmed_memory VALUES (?, ?, ?, ?)",
                (memory.id, printer_id, memory.investigation_id, memory.json()),
            )

    def delete(self, printer_id: str, memory_id: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "DELETE FROM confirmed_memory WHERE printer_id=? AND id=?", (printer_id, memory_id)
            )
