"""Transactions shared by investigation turns and replayable requests."""

from __future__ import annotations

import sqlite3

from klipperai_agent.domain.investigation import Investigation
from klipperai_agent.domain.redaction import redact_text
from klipperai_agent.domain.repositories import InvestigationConflict


def ensure_revision(db: sqlite3.Connection, investigation: Investigation) -> None:
    if investigation.revision == 0:
        db.execute(
            "INSERT OR IGNORE INTO investigations VALUES (?, ?, ?, ?, ?, 0)",
            (
                investigation.id,
                investigation.printer_id,
                redact_text(investigation.title),
                investigation.created_at,
                investigation.updated_at,
            ),
        )
    row = db.execute(
        "SELECT revision FROM investigations WHERE id=? AND printer_id=?",
        (investigation.id, investigation.printer_id),
    ).fetchone()
    if row is None or row[0] != investigation.revision:
        raise InvestigationConflict("This conversation changed. Reload it before retrying.")
