"""A separate, single-use historical permit and reservation journal."""

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .contracts import Model, canonical
from .historical_pilot_contract import hash_bytes
from .isolated_study_contract import BASE, Hash

APP_ID = 0x544C3535
SCHEMA = """
PRAGMA application_id=1414280501;
PRAGMA user_version=1;
CREATE TABLE permits (
    id TEXT PRIMARY KEY, scope TEXT UNIQUE NOT NULL, receipt TEXT NOT NULL,
    confirmation TEXT NOT NULL
);
CREATE TABLE runs (
    permit TEXT PRIMARY KEY REFERENCES permits(id),
    scratch TEXT NOT NULL,
    job TEXT,
    state TEXT NOT NULL CHECK(state IN ('RESERVED','SEALED','UNKNOWN')),
    bundle_sha TEXT,
    CHECK(
        (state='RESERVED' AND bundle_sha IS NULL)
        OR (state='SEALED' AND bundle_sha IS NOT NULL AND job IS NOT NULL)
        OR (state='UNKNOWN' AND bundle_sha IS NULL)
    )
);
CREATE TRIGGER no_replace_permit BEFORE INSERT ON permits
WHEN EXISTS(SELECT 1 FROM permits WHERE id=NEW.id OR scope=NEW.scope)
BEGIN SELECT RAISE(ABORT, 'historical permit already exists'); END;
CREATE TRIGGER no_replace_run BEFORE INSERT ON runs
WHEN EXISTS(SELECT 1 FROM runs WHERE permit=NEW.permit)
BEGIN SELECT RAISE(ABORT, 'historical reservation already exists'); END;
CREATE TRIGGER no_permit_update BEFORE UPDATE ON permits
BEGIN SELECT RAISE(ABORT, 'immutable historical permit'); END;
CREATE TRIGGER no_permit_delete BEFORE DELETE ON permits
BEGIN SELECT RAISE(ABORT, 'immutable historical permit'); END;
CREATE TRIGGER enforce_initial_run BEFORE INSERT ON runs
WHEN NEW.state!='RESERVED' OR NEW.job IS NOT NULL OR NEW.bundle_sha IS NOT NULL
    OR NOT EXISTS(SELECT 1 FROM permits WHERE id=NEW.permit)
BEGIN SELECT RAISE(ABORT, 'historical run requires an initial reservation'); END;
CREATE TRIGGER no_run_delete BEFORE DELETE ON runs
BEGIN SELECT RAISE(ABORT, 'historical reservation is consumed'); END;
CREATE TRIGGER enforce_run_transition BEFORE UPDATE ON runs
WHEN OLD.state!='RESERVED' OR NEW.permit!=OLD.permit OR NEW.scratch!=OLD.scratch
    OR (OLD.job IS NOT NULL AND NEW.job IS NOT OLD.job)
    OR (NEW.state='RESERVED' AND (OLD.job IS NOT NULL OR NEW.job IS NULL))
BEGIN SELECT RAISE(ABORT, 'invalid historical reservation transition'); END;
"""


class Permit(Model):
    schema_version: Literal["1.0"] = "1.0"
    purpose: Literal["HISTORICAL_BACKTEST_ONCE", "SYNTHETIC_BACKTEST_ONCE"]
    issue_number: Literal[3] = 3
    pilot_commit: Literal[BASE] = BASE
    attempt_id: Annotated[str, Field(pattern=r"^attempt_[a-f0-9]{32}$")]
    implementation_receipt_sha256: Hash
    job_sha256: Hash
    operator: Annotated[str, Field(min_length=1, max_length=120)]
    operator_sid: Annotated[str, Field(pattern=r"^S-1-(?:[0-9]+-)*[0-9]+$")]
    approved_at: datetime

    @model_validator(mode="after")
    def validate_time(self):
        if self.approved_at.utcoffset() != UTC.utcoffset(None) or self.approved_at > datetime.now(
            UTC
        ):
            raise ValueError("Approval timestamp is not past UTC")
        return self

    @property
    def scope(self):
        if self.purpose == "HISTORICAL_BACKTEST_ONCE":
            return f"issue-3:{self.attempt_id}"
        return f"synthetic:{self.job_sha256}"


def phrase(permit):
    return f"AUTHORIZE {permit.purpose} {permit.attempt_id} {permit.job_sha256}"


def receipt_id(permit):
    return hash_bytes(canonical(permit.model_dump(mode="json")).encode())


@contextmanager
def transaction(path):
    if path.name != "historical-pilot.sqlite3":
        raise ValueError("A dedicated historical-pilot.sqlite3 is required")
    conn = sqlite3.connect(path.absolute().as_uri() + "?mode=rw", uri=True, timeout=5)
    try:
        if (
            conn.execute("PRAGMA application_id").fetchone()[0] != APP_ID
            or conn.execute("PRAGMA user_version").fetchone()[0] != 1
        ):
            raise ValueError("Unrecognized historical authorization database")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("BEGIN IMMEDIATE")
        with conn:
            yield conn
    finally:
        conn.close()


def initialize(path):
    if path.name != "historical-pilot.sqlite3":
        raise ValueError("A dedicated historical-pilot.sqlite3 is required")
    with path.open("xb"):
        pass
    conn = sqlite3.connect(path)
    try:
        conn.executescript("BEGIN IMMEDIATE;" + SCHEMA + "COMMIT;")
    finally:
        conn.close()


def grant(path, permit, confirmation):
    if confirmation != phrase(permit):
        raise ValueError("Explicit historical confirmation did not match")
    key = receipt_id(permit)
    with transaction(path) as conn:
        conn.execute(
            "INSERT INTO permits VALUES (?, ?, ?, ?)",
            (key, permit.scope, canonical(permit.model_dump(mode="json")), confirmation),
        )
    return key


def reserve(path, permit_id, job_sha256, purpose, scratch, binding=None):
    with transaction(path) as conn:
        row = conn.execute(
            "SELECT receipt,confirmation FROM permits WHERE id=?", (permit_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Explicit historical permit required")
        permit = Permit.model_validate_json(row[0])
        if row[1] != phrase(permit) or (receipt_id(permit), permit.job_sha256, permit.purpose) != (
            permit_id,
            job_sha256,
            purpose,
        ):
            raise ValueError("Permit integrity or sealed execution scope mismatch")
        if purpose == "HISTORICAL_BACKTEST_ONCE" and binding != (
            permit.attempt_id,
            permit.implementation_receipt_sha256,
            permit.operator,
            permit.operator_sid,
        ):
            raise ValueError(
                "Historical permit does not match the verified pilot and Windows operator"
            )
        run = conn.execute(
            "SELECT scratch,job,state,bundle_sha FROM runs WHERE permit=?", (permit_id,)
        ).fetchone()
        if run is None:
            conn.execute(
                "INSERT INTO runs(permit,scratch,state) VALUES (?,?,'RESERVED')",
                (permit_id, scratch),
            )
            return True, (None, "RESERVED", None)
        if run[0] != scratch:
            raise ValueError("The consumed reservation belongs to a different scratch identity")
        return False, run[1:]


def bind_job(path, permit_id, identity):
    with transaction(path) as conn:
        cursor = conn.execute(
            "UPDATE runs SET job=? WHERE permit=? AND state='RESERVED' AND job IS NULL",
            (identity, permit_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Historical reservation is not bindable")


def finish(path, permit_id, *, bundle_sha=None):
    state = "SEALED" if bundle_sha is not None else "UNKNOWN"
    with transaction(path) as conn:
        cursor = conn.execute(
            "UPDATE runs SET state=?,bundle_sha=? WHERE permit=? AND state='RESERVED'",
            (state, bundle_sha, permit_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Historical reservation is already terminal or uncertain")


def synthetic_key(path, scope):
    with transaction(path) as conn:
        row = conn.execute("SELECT id,scope FROM permits").fetchall()
        if len(row) != 1 or row[0][1] != scope:
            raise ValueError("Use the same isolated synthetic registry for replay")
        return row[0][0]


def assert_unconsumed(path, scope):
    """Check the designated registry without creating a database or a journal."""
    if path.name != "historical-pilot.sqlite3" or not path.parent.is_dir():
        raise ValueError("A pre-provisioned historical registry directory is required")
    try:
        path.lstat()
    except FileNotFoundError:
        return
    conn = sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        conn.execute("PRAGMA query_only=ON")
        if (
            conn.execute("PRAGMA application_id").fetchone()[0] != APP_ID
            or conn.execute("PRAGMA user_version").fetchone()[0] != 1
        ):
            raise ValueError("Unrecognized historical authorization database")
        if conn.execute(
            "SELECT 1 FROM permits JOIN runs ON permits.id=runs.permit WHERE permits.scope=?",
            (scope,),
        ).fetchone():
            raise ValueError("The designated historical permit was already consumed")
    finally:
        conn.close()
