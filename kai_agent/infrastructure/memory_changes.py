"""Atomic memory mutations in KAI storage, never in printer files."""

import sqlite3

from kai_agent.domain.investigation import ConfirmedMemory, utc_now
from kai_agent.domain.memory import MemoryUpdate
from kai_agent.domain.redaction import redact_data
from kai_agent.domain.repositories import InvestigationConflict


def apply_memory_changes(
    db: sqlite3.Connection, printer_id: str, changes: list[MemoryUpdate]
) -> list[MemoryUpdate]:
    applied = []
    for change in changes:
        row = db.execute(
            "SELECT content FROM confirmed_memory WHERE printer_id=? AND id=?",
            (printer_id, change.id),
        ).fetchone()
        old = ConfirmedMemory.parse_raw(row[0]) if row else None
        if change.action != "add" and (
            old is None or old.revision != change.expected_revision
            or old.content != change.before_content
        ):
            raise InvestigationConflict("Memory changed in another window. Reload before editing.")
        if change.action == "forget":
            db.execute("DELETE FROM confirmed_memory WHERE printer_id=? AND id=?", (printer_id, change.id))
        else:
            if change.action == "add":
                if old is not None:
                    raise InvestigationConflict("This memory already exists.")
                rows = db.execute("SELECT content FROM confirmed_memory WHERE printer_id=?", (printer_id,)).fetchall()
                normalized = " ".join(change.content.casefold().split())
                if any(" ".join(ConfirmedMemory.parse_raw(item[0]).content.casefold().split()) == normalized for item in rows):
                    continue
                if len(rows) >= 100:
                    raise InvestigationConflict("Memory is full. Forget an outdated entry first.")
            note = ConfirmedMemory(
                id=change.id, kind=change.kind, content=change.content, confirmed_at=utc_now(),
                revision=(old.revision + 1) if old else 0, origin=change.origin,
                source_quote=change.source_quote, source_chat_id=change.source_chat_id,
                investigation_id=old.investigation_id if old and change.origin == "manual" else None,
                evidence=old.evidence if old else [],
            )
            note = ConfirmedMemory.parse_obj(redact_data(note.model_dump()))
            if old:
                db.execute(
                    "UPDATE confirmed_memory SET investigation_id=?, content=? WHERE printer_id=? AND id=?",
                    (note.investigation_id, note.json(), printer_id, note.id),
                )
            else:
                db.execute("INSERT INTO confirmed_memory VALUES (?, ?, ?, ?)", (note.id, printer_id, note.investigation_id, note.json()))
        applied.append(change)
    return applied
