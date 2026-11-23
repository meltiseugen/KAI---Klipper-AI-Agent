"""Explicit user statements are retained until forgotten, separately from expiring evidence."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Callable

from kai_agent.domain.investigation import ConfirmedMemory
from kai_agent.domain.memory import MemoryUpdate
from kai_agent.domain.redaction import redact_data
from kai_agent.domain.repositories import InvestigationConflict
from kai_agent.infrastructure.memory_changes import apply_memory_changes


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
        notes = [
            ConfirmedMemory.parse_obj(redact_data(ConfirmedMemory.parse_raw(row[0]).model_dump()))
            for row in rows
        ]
        return sorted(notes, key=lambda note: note.confirmed_at, reverse=True)

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

    def update(self, printer_id: str, memory_id: str, content: str, revision: int) -> ConfirmedMemory:
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT content FROM confirmed_memory WHERE printer_id=? AND id=?", (printer_id, memory_id)).fetchone()
            if row is None:
                raise InvestigationConflict("This memory was removed. Reload memories.")
            old = ConfirmedMemory.parse_raw(row[0])
            apply_memory_changes(db, printer_id, [MemoryUpdate(
                id=old.id, action="update", kind=old.kind, content=content,
                before_content=old.content, expected_revision=revision,
                origin="manual", source_chat_id=old.source_chat_id,
            )])
            updated = db.execute("SELECT content FROM confirmed_memory WHERE printer_id=? AND id=?", (printer_id, memory_id)).fetchone()
            return ConfirmedMemory.parse_raw(updated[0])
