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

    def ingest(self, bundle: Bundle, source, *, sealed_source=None, receipt_sha256=None):
        source = str(source)
        bundle = Bundle.model_validate_json(bundle.model_dump_json())
        document = bundle.model_dump(mode="json")
        sealed = sealed_source is not None or receipt_sha256 is not None
        if sealed:
            from .ingestion import preview

            if sealed_source is None or receipt_sha256 is None:
                raise IntegrityError("Sealed source and reviewed receipt hash are both required")
            verified = preview(source, sealed_source, receipt_sha256)
            if verified.model_dump(mode="json") != document:
                raise IntegrityError("Bundle differs from the verified sealed source")
        elif any(
            r["audit_status"] != "UNVERIFIED"
            for table in ("runs", "case_results")
            for r in document[table]
        ):
            raise IntegrityError("Generic ingestion cannot accredit source audits")
        # A request for file integrity is only credited after checking captured bytes.
        from .verification import read, sha

        for artifact in document["artifacts"]:
            if artifact["verification_status"] == "HASH_VERIFIED":
                if sha(read(artifact["reference"])) != artifact["sha256"]:
                    raise IntegrityError("Artifact hash does not match captured source bytes")
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
                            self._accredit(
                                c, table, record, source, sealed, sealed_source, receipt_sha256
                            )
                            continue
                        columns = ["id", "payload", "sha256", "registered_at_utc", *refs]
                        values = [record["id"], raw, hashed, now(), *(record[k] for k in refs)]
                        marks = ",".join("?" for _ in values)
                        c.execute(
                            f"INSERT INTO {table}({','.join(columns)}) VALUES({marks})", values
                        )
                        self._event(c, "REGISTERED_" + table.upper(), source, hashed)
                        self._accredit(
                            c, table, record, source, sealed, sealed_source, receipt_sha256
                        )
                        added += 1
                self._event(c, "INGESTED" if added else "DUPLICATE", source, digest)
        except (Conflict, sqlite3.IntegrityError):
            with self.connection(write=True) as c:
                self._event(c, "CONFLICT", source, digest)
            raise Conflict("Ingestion conflict; scientific records rolled back") from None
        return {"status": "INGESTED" if added else "DUPLICATE", "added": added}

    def _accredit(self, c, table, record, source, sealed, sealed_source, receipt_sha256):
        if sealed and table in ("runs", "case_results"):
            kind = "SOURCE_AUDITED_" + table
            provenance = canonical(
                {
                    "source": str(Path(source).absolute()),
                    "receipt": str(Path(sealed_source).absolute()),
                    "receipt_sha256": receipt_sha256,
                }
            )
        elif table == "artifacts" and record["verification_status"] == "HASH_VERIFIED":
            kind, provenance = "HASH_VERIFIED_artifacts", record["reference"]
        else:
            return
        hashed = fingerprint(record)
        if not c.execute(
            "SELECT 1 FROM catalog_events WHERE kind=? AND fingerprint=?", (kind, hashed)
        ).fetchone():
            self._event(c, kind, provenance, hashed)

    def accreditations(self):
        with self.connection() as c:
            return set(
                c.execute(
                    "SELECT kind,fingerprint FROM catalog_events "
                    "WHERE kind IN ('SOURCE_AUDITED_runs','SOURCE_AUDITED_case_results',"
                    "'HASH_VERIFIED_artifacts')"
                ).fetchall()
            )

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

    def records(self, table, *, declarations=False):
        import json

        if table not in REFERENCES:
            raise ValueError("Unknown catalogue entity")
        with self.connection() as c:
            records = [
                json.loads(r[0]) for r in c.execute(f"SELECT payload FROM {table} ORDER BY id")
            ]
            accredited = set(
                c.execute(
                    "SELECT kind,fingerprint FROM catalog_events "
                    "WHERE kind LIKE 'SOURCE_AUDITED_%' "
                    "OR kind='HASH_VERIFIED_artifacts'"
                ).fetchall()
            )
        if not declarations:
            for record in records:
                if table in ("runs", "case_results"):
                    if ("SOURCE_AUDITED_" + table, fingerprint(record)) not in accredited:
                        record["audit_status"] = "UNVERIFIED"
                elif table == "artifacts":
                    if ("HASH_VERIFIED_artifacts", fingerprint(record)) not in accredited:
                        record["verification_status"] = "UNVERIFIED"
        return records

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
