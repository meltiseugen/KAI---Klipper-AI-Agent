"""Bounded, versioned knowledge storage in the application's own SQLite database."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from klipperai_agent.domain.knowledge import CachedDocument, KnowledgeConflict, KnowledgeSetup
from klipperai_agent.infrastructure.private_files import open_private_file


class SqliteKnowledgeRepository:
    def __init__(self, data_dir: Path, printer_id: str, protected_dirs: tuple[Path, ...]):
        self._path = data_dir.resolve() / "knowledge.sqlite3"
        self._printer = printer_id
        self._protected = tuple(path.resolve() for path in protected_dirs)
        self._check()
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        open_private_file(self._path).close()
        with closing(self._connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS setups (printer TEXT PRIMARY KEY, content TEXT NOT NULL, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS documents (printer TEXT NOT NULL, id TEXT NOT NULL, digest TEXT NOT NULL, content TEXT NOT NULL, original BLOB NOT NULL, PRIMARY KEY(printer,id,digest));
            """)
        self._path.chmod(0o600)

    def _check(self) -> None:
        for suffix in ("", "-journal", "-wal", "-shm"):
            path = Path(str(self._path) + suffix)
            if (
                path.is_symlink()
                or (path.exists() and path.stat().st_nlink > 1)
                or any(path.resolve().is_relative_to(root) for root in self._protected)
            ):
                raise ValueError(
                    "Knowledge storage must stay outside printer files and reject redirected database files."
                )

    def _connect(self) -> sqlite3.Connection:
        self._check()
        return sqlite3.connect(self._path, timeout=5)

    def setup(self) -> KnowledgeSetup | None:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT content FROM setups WHERE printer=?", (self._printer,)
            ).fetchone()
        return KnowledgeSetup.parse_raw(row[0]) if row else None

    def save_setup(self, setup: KnowledgeSetup) -> KnowledgeSetup:
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT revision FROM setups WHERE printer=?", (self._printer,)
            ).fetchone()
            if setup.revision != (row[0] if row else 0):
                raise KnowledgeConflict(
                    "Printer knowledge changed in another window. Reload it before saving."
                )
            updated = setup.copy(update={"revision": setup.revision + 1})
            db.execute(
                "INSERT OR REPLACE INTO setups VALUES (?,?,?)",
                (self._printer, updated.json(), updated.revision),
            )
        return updated

    def documents(self) -> list[CachedDocument]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT content FROM documents WHERE rowid IN (SELECT max(rowid) FROM documents WHERE printer=? GROUP BY id)",
                (self._printer,),
            ).fetchall()
        return [CachedDocument.parse_raw(row[0]) for row in rows]

    def save_document(self, document: CachedDocument, original: bytes) -> None:
        if len(original) > 8 * 1024 * 1024 or len(document.content) > 300000:
            raise ValueError("Knowledge document exceeds storage bounds.")
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?)",
                (self._printer, document.id, document.digest, document.json(), original),
            )
            db.execute(
                "DELETE FROM documents WHERE printer=? AND id=? AND rowid NOT IN (SELECT rowid FROM documents WHERE printer=? AND id=? ORDER BY rowid DESC LIMIT 2)",
                (self._printer, document.id, self._printer, document.id),
            )
            total = db.execute(
                "SELECT coalesce(sum(length(original)),0), count(*) FROM documents WHERE printer=?",
                (self._printer,),
            ).fetchone()
            if total[0] > 128 * 1024 * 1024 or total[1] > 72:
                raise ValueError("Printer knowledge cache quota reached.")

    def original(self, document_id: str, digest: str | None = None) -> bytes | None:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT original FROM documents WHERE printer=? AND id=? AND (? IS NULL OR digest=?) ORDER BY rowid DESC LIMIT 1",
                (self._printer, document_id, digest, digest),
            ).fetchone()
        return bytes(row[0]) if row else None

    def retain_components(self, keys: set[str]) -> None:
        self._prune(lambda doc: doc.component_key in keys)

    def retain_sources(self, component_key: str, ids: set[str]) -> None:
        self._prune(lambda doc: doc.component_key != component_key or doc.id in ids)

    def _prune(self, keep) -> None:
        with closing(self._connect()) as db, db:
            rows = db.execute(
                "SELECT rowid,content FROM documents WHERE printer=?", (self._printer,)
            ).fetchall()
            for rowid, content in rows:
                if not keep(CachedDocument.parse_raw(content)):
                    db.execute("DELETE FROM documents WHERE rowid=?", (rowid,))
