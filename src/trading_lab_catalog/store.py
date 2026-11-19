"""Dedicated SQLite with explicit initialization and atomic, immutable ingestion."""

import os
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from .models import Bundle, canonical, fingerprint, now
from .schema import APPLICATION_ID, REFERENCES, VERSION, ddl


class Conflict(ValueError):
    pass


class IntegrityError(ValueError):
    pass


def default_path():
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / (
        "TradingLab/StrategyCatalog/strategy-catalog.sqlite3"
    )


class Store:
    def __init__(self, path):
        self.path = Path(path).absolute()
        if self.path.name != "strategy-catalog.sqlite3":
            raise ValueError("A dedicated strategy-catalog.sqlite3 is required")
        for part in (self.path, *self.path.parents):
            if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
                raise ValueError("Catalogue paths must not traverse links")

    def _location(self):
        if self.path.parent.exists() and any(
            p.name not in {self.path.name, self.path.name + "-journal"}
            for p in self.path.parent.iterdir()
        ):
            raise ValueError("Catalogue requires a dedicated directory")

    def init(self):
        self._location()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            with self.connection():
                return
        # SQLite serializes concurrent initializers. Existing foreign DBs are
        # rejected before any schema or journal-mode mutation.
        with closing(sqlite3.connect(self.path, timeout=10)) as c, c:
            c.execute("BEGIN IMMEDIATE")
            app = c.execute("PRAGMA application_id").fetchone()[0]
            if app == APPLICATION_ID:
                self._check(c)
                return
            if app or c.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]:
                raise IntegrityError("Existing database is not an empty catalogue")
            for statement in ddl():
                c.execute(statement)
            c.execute(f"PRAGMA application_id={APPLICATION_ID}")
            c.execute(f"PRAGMA user_version={VERSION}")

    @staticmethod
    def _check(c):
        if (
            c.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
            or c.execute("PRAGMA user_version").fetchone()[0] != VERSION
        ):
            raise IntegrityError("Unknown catalogue identity/schema; explicit migration required")

    def migrate(self, target=VERSION):
        if target != VERSION:
            raise IntegrityError("No migration to the requested schema is defined")
        with self.connection():
            return VERSION

    @contextmanager
    def connection(self, *, write=False):
        self._location()
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        with self.path.open("rb") as raw:
            header = raw.read(100)
        if header[18:20] != b"\x01\x01" or (
            not write
            and any(
                self.path.with_name(self.path.name + suffix).exists()
                for suffix in ("-wal", "-shm", "-journal")
            )
        ):
            raise IntegrityError("WAL or pending journal requires review")
        c = sqlite3.connect(
            self.path.as_uri() + ("?mode=rw" if write else "?mode=ro"), uri=True, timeout=10
        )
        try:
            self._check(c)
            c.execute("PRAGMA foreign_keys=ON")
            if write:
                c.execute("PRAGMA synchronous=FULL")
                c.execute("BEGIN IMMEDIATE")
            else:
                c.execute("PRAGMA query_only=ON")
                c.execute("BEGIN")
            yield c
            if write:
                c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    @staticmethod
    def _event(c, kind, source, digest):
        c.execute(
            "INSERT INTO catalog_events(kind,source,fingerprint,occurred_at_utc) VALUES(?,?,?,?)",
            (kind, source, digest, now()),
        )

    def ingest(self, bundle: Bundle, source):
        bundle = Bundle.model_validate_json(bundle.model_dump_json())
        document = bundle.model_dump(mode="json")
        digest = fingerprint(document)
        added = 0
        try:
            with self.connection(write=True) as c:
                for table, refs in REFERENCES.items():
                    for record in document[table]:
                        if table == "research_decisions":
                            self._decision_lineage(c, record)
                        raw, hashed = canonical(record), fingerprint(record)
                        old = c.execute(
                            f"SELECT payload FROM {table} WHERE id=?", (record["id"],)
                        ).fetchone()
                        if old:
                            if old[0] != raw:
                                raise Conflict(f"Conflicting {table} identity")
                            continue
                        columns = ["id", "payload", "sha256", "registered_at_utc", *refs]
                        values = [record["id"], raw, hashed, now(), *(record[k] for k in refs)]
                        marks = ",".join("?" for _ in values)
                        c.execute(
                            f"INSERT INTO {table}({','.join(columns)}) VALUES({marks})", values
                        )
                        self._event(c, "REGISTERED_" + table.upper(), source, hashed)
                        added += 1
                self._event(c, "INGESTED" if added else "DUPLICATE", source, digest)
        except (Conflict, sqlite3.IntegrityError):
            with self.connection(write=True) as c:
                self._event(c, "CONFLICT", source, digest)
            raise Conflict("Ingestion conflict; scientific records rolled back") from None
        return {"status": "INGESTED" if added else "DUPLICATE", "added": added}

    @staticmethod
    def _decision_lineage(c, decision):
        version = decision["version_id"]
        if decision["run_id"]:
            row = c.execute(
                "SELECT e.version_id FROM runs r JOIN experiments e ON e.id=r.experiment_id "
                "WHERE r.id=?",
                (decision["run_id"],),
            ).fetchone()
            if row is None or (version is not None and version != row[0]):
                raise Conflict("Decision refers to a different run/version")
            version = row[0]
        if version:
            row = c.execute("SELECT strategy_id FROM versions WHERE id=?", (version,)).fetchone()
            if row is None or row[0] != decision["strategy_id"]:
                raise Conflict("Decision refers to a different strategy")

    def records(self, table):
        import json

        if table not in REFERENCES:
            raise ValueError("Unknown catalogue entity")
        with self.connection() as c:
            return [json.loads(r[0]) for r in c.execute(f"SELECT payload FROM {table} ORDER BY id")]

    def verify(self):
        with self.connection() as c:
            if (
                c.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                or c.execute("PRAGMA foreign_key_check").fetchall()
            ):
                raise IntegrityError("SQLite integrity failure")
            for table in REFERENCES:
                for raw, digest in c.execute(f"SELECT payload,sha256 FROM {table}"):
                    import json

                    if fingerprint(json.loads(raw)) != digest:
                        raise IntegrityError("Catalogue payload changed")
        return {"status": "OK", "schema": VERSION}

    def record_verification(self, result):
        with self.connection(write=True) as c:
            self._event(c, "VERIFIED", "operator verification", fingerprint(result))
