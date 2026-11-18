"""Existing coordinator queries through SQLite read-only snapshots; no initialization."""

import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from .store import APPLICATION_ID, SCHEMA_VERSION, Store


class ReadOnlyStore(Store):
    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self._snapshot = None
        if not self.path.is_file():
            raise FileNotFoundError("Existing orchestration database required: " + str(self.path))

    @contextmanager
    def _open_reader(self):
        with closing(
            sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=15)
        ) as conn:
            yield conn

    @contextmanager
    def _reader(self):
        with self._open_reader() as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            if conn.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                raise ValueError("Not an orchestration database")
            if conn.execute("PRAGMA user_version").fetchone()[0] not in (5, 6, SCHEMA_VERSION):
                raise ValueError(
                    "Unsupported schema for read-only verification; no migration performed"
                )
            yield conn

    @contextmanager
    def connection(self):
        if self._snapshot is not None:
            yield self._snapshot
        else:
            with self._reader() as conn:
                yield conn

    @contextmanager
    def snapshot(self):
        if self._snapshot is not None:
            raise ValueError("Use one ReadOnlyStore per verification")
        with self._reader() as conn:
            conn.execute("BEGIN")
            self._snapshot = conn
            try:
                yield self
            finally:
                self._snapshot = None
                conn.rollback()  # End the read transaction, never commit writes.

    def transaction(self):
        raise ValueError("Integrated verification prohibits write transactions")
