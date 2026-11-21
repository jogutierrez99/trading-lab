"""Private bounded SQL adapter using one existing guarded read transaction."""

import sqlite3
from contextlib import contextmanager

from pydantic import ValidationError

from .models import Artifact, Case, Decision, Experiment, Run, Strategy, Version, fingerprint
from .read_models import ReadFailure
from .schema import REFERENCES, ddl
from .store import Conflict, Store
from .verification import parse

MODELS = dict(
    strategies=Strategy,
    versions=Version,
    experiments=Experiment,
    runs=Run,
    case_results=Case,
    artifacts=Artifact,
    research_decisions=Decision,
)


def marks(values):
    return ",".join("?" for _ in values)


class Snapshot:
    def __init__(self, connection):
        self.c = connection
        self.scope = {table: [] for table in REFERENCES}
        self._captured_hashes = set()
        schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"
        ).fetchall()
        if {r[0] for r in schema} != set(ddl()):
            raise ReadFailure("BLOCKED", "Unexpected catalogue structure")
        counts = {
            table: connection.execute("SELECT count(*) FROM " + table).fetchone()[0]
            for table in (*REFERENCES, "catalog_events")
        }
        self.counts = counts
        self.checkpoint = fingerprint(
            {
                "counts": counts,
                "event": connection.execute("SELECT max(event_id) FROM catalog_events").fetchone()[
                    0
                ],
                "schema": fingerprint(sorted(r[0] for r in schema)),
            }
        )

    @contextmanager
    def connection(self):
        yield self.c

    verify = Store.verify

    def accreditations(self):
        # Project events only for validated selected records. Classification
        # remains in Store.records and service.joined_cases, unchanged.
        hashes = sorted(self._captured_hashes)
        result = set()
        for offset in range(0, len(hashes), 200):
            chunk = hashes[offset : offset + 200]
            result.update(
                self.c.execute(
                    "SELECT kind,fingerprint FROM catalog_events WHERE fingerprint IN ("
                    + marks(chunk)
                    + ")",
                    chunk,
                ).fetchall()
            )
        return result

    def load(self, table, identities, *, declarations=False):
        if table not in MODELS or len(identities) > 200:
            raise ReadFailure("RESPONSE_LIMIT_EXCEEDED", "Related entity limit is 200")
        if not identities:
            return []
        size = (
            self.c.execute(
                f"SELECT sum(length(CAST(payload AS BLOB))) FROM {table} "
                f"WHERE id IN ({marks(identities)})",
                identities,
            ).fetchone()[0]
            or 0
        )
        if size > 4 * 1024 * 1024:
            raise ReadFailure("RESPONSE_LIMIT_EXCEEDED", "Related records exceed read limit")
        relational = "," + ",".join(REFERENCES[table]) if REFERENCES[table] else ""
        rows = self.c.execute(
            f"SELECT id,payload,sha256{relational} FROM {table} WHERE id IN ({marks(identities)})",
            identities,
        ).fetchall()
        for identity, raw, digest, *relations in rows:
            if len(raw.encode()) > 1024 * 1024:
                raise ReadFailure("RESPONSE_LIMIT_EXCEEDED", "Stored record exceeds read limit")
            try:
                record = parse(raw)
                MODELS[table].model_validate_json(raw)
            except (ValueError, ValidationError):
                raise ReadFailure("INTEGRITY_ERROR", "Invalid stored contract") from None
            if fingerprint(record) != digest or record.get("id") != identity:
                raise ReadFailure("INTEGRITY_ERROR", "Stored record fingerprint mismatch")
            if any(
                record[key] != value
                for key, value in zip(REFERENCES[table], relations, strict=True)
            ):
                raise ReadFailure("INTEGRITY_ERROR", "Contradictory stored relationship")
            self._captured_hashes.add(digest)
            for key, parent in REFERENCES[table].items():
                if (
                    record[key] is not None
                    and not self.c.execute(
                        f"SELECT 1 FROM {parent} WHERE id=?", (record[key],)
                    ).fetchone()
                ):
                    raise ReadFailure("INTEGRITY_ERROR", "Missing related entity")
            if table == "research_decisions":
                try:
                    Store._decision_lineage(self.c, record)
                except Conflict:
                    raise ReadFailure("INTEGRITY_ERROR", "Contradictory decision lineage") from None
        return Store.records(self, table, declarations=declarations, ids=identities)

    def records(self, table, *, declarations=False):
        return self.load(table, self.scope[table], declarations=declarations)

    def require(self, table, identity):
        rows = self.load(table, [identity])
        if not rows:
            raise ReadFailure("NOT_FOUND", "Catalogue identity was not found")
        return rows[0]

    def ids(self, table, where="", parameters=(), *, limit=201):
        # table/where are internal constants assembled only from allowlisted fields.
        if table not in MODELS:
            raise ValueError("Unknown internal entity")
        return [
            r[0]
            for r in self.c.execute(
                f"SELECT t.id FROM {table} t {where} ORDER BY t.id LIMIT ?", (*parameters, limit)
            )
        ]

    def graph(self, case_ids):
        self.scope["case_results"] = case_ids
        cases = self.records("case_results", declarations=True)
        self.scope["runs"] = sorted({r["run_id"] for r in cases})
        runs = self.records("runs", declarations=True)
        self.scope["experiments"] = sorted({r["experiment_id"] for r in runs})
        experiments = self.records("experiments")
        self.scope["versions"] = sorted({r["version_id"] for r in experiments})
        versions = self.records("versions")
        self.scope["strategies"] = sorted({r["strategy_id"] for r in versions})
        strategies = self.records("strategies")
        if (
            len(runs) != len(self.scope["runs"])
            or len(experiments) != len(self.scope["experiments"])
            or len(versions) != len(self.scope["versions"])
            or len(strategies) != len(self.scope["strategies"])
        ):
            raise ReadFailure("INTEGRITY_ERROR", "Missing related entity")
        self.scope["research_decisions"] = self.applicable_decision_ids(
            self.scope["strategies"], self.scope["versions"], self.scope["runs"]
        )

    def applicable_decision_ids(self, strategies, versions, runs):
        if not strategies or not versions or not runs:
            return []
        return self.ids(
            "research_decisions",
            f"WHERE t.strategy_id IN ({marks(strategies)}) "
            f"AND (t.version_id IS NULL OR t.version_id IN ({marks(versions)})) "
            f"AND (t.run_id IS NULL OR t.run_id IN ({marks(runs)}))",
            [*strategies, *versions, *runs],
        )

    def scoped_ids(self, table, foreign_key, identity):
        if foreign_key not in REFERENCES[table]:
            raise ValueError("Unknown relationship")
        result = self.ids(table, f"WHERE t.{foreign_key}=?", (identity,))
        if len(result) > 200:
            raise ReadFailure("RESPONSE_LIMIT_EXCEEDED", "Related entity limit is 200")
        return result


def read_authorizer(action, arg1, arg2, database, trigger):
    if action in {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
        sqlite3.SQLITE_TRANSACTION,
        sqlite3.SQLITE_RECURSIVE,
    }:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and arg2 is None:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY
