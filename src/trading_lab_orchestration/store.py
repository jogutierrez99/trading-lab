"""Transactional manual intake. No dependency on the lab, network or workers."""

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .contracts import HypothesisManifest, canonical, digest
from .migration import migrate_v2, migrate_v3, migrate_v4

APPLICATION_ID = 0x544C4F31  # TLO1; reject experiment/forward SQLite files.
SCHEMA_VERSION = 7
TRANSITIONS = {
    "HYPOTHESIS_READY": {"BLOCKED", "CANCELLED", "ARCHIVED"},
    "BLOCKED": {"HYPOTHESIS_READY", "CANCELLED", "ARCHIVED"},
    "CANCELLED": {"ARCHIVED"},
    "ARCHIVED": set(),
}
TASK_STATE = {
    "HYPOTHESIS_READY": "QUEUED",
    "BLOCKED": "BLOCKED",
    "CANCELLED": "CANCELLED",
    "ARCHIVED": "CANCELLED",
}
DDL = (
    """CREATE TABLE candidates (
        candidate_id TEXT PRIMARY KEY,
        hypothesis_id TEXT NOT NULL UNIQUE,
        fingerprint TEXT NOT NULL UNIQUE,
        manifest_json TEXT NOT NULL,
        manifest_sha256 TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN
            ('HYPOTHESIS_READY','BLOCKED','CANCELLED','ARCHIVED')),
        created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL)""",
    """CREATE TABLE tasks (
        task_id TEXT PRIMARY KEY,
        candidate_id TEXT NOT NULL UNIQUE REFERENCES candidates(candidate_id),
        idempotency_key TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL CHECK(kind='MANUAL_REVIEW'),
        mode TEXT NOT NULL CHECK(mode='PREPARE_ONLY'),
        status TEXT NOT NULL CHECK(status IN ('QUEUED','BLOCKED','CANCELLED')),
        created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL)""",
    """CREATE TABLE submissions (
        hypothesis_id TEXT PRIMARY KEY,
        candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
        manifest_json TEXT NOT NULL, manifest_sha256 TEXT NOT NULL,
        created_at_utc TEXT NOT NULL)""",
    """CREATE TABLE events (
        event_id INTEGER PRIMARY KEY,
        candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
        task_id TEXT REFERENCES tasks(task_id),
        entity TEXT NOT NULL CHECK(entity IN ('candidate','task','submission')),
        old_state TEXT, new_state TEXT NOT NULL,
        actor TEXT NOT NULL, reason TEXT NOT NULL,
        created_at_utc TEXT NOT NULL,
        payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL)""",
    "CREATE INDEX events_candidate ON events(candidate_id, event_id)",
    """CREATE TRIGGER immutable_manifest BEFORE UPDATE OF candidate_id, hypothesis_id,
        fingerprint, manifest_json, manifest_sha256, created_at_utc ON candidates
        BEGIN SELECT RAISE(ABORT, 'immutable candidate snapshot'); END""",
    """CREATE TRIGGER immutable_events_update BEFORE UPDATE ON events
        BEGIN SELECT RAISE(ABORT, 'immutable event'); END""",
    """CREATE TRIGGER immutable_events_delete BEFORE DELETE ON events
        BEGIN SELECT RAISE(ABORT, 'immutable event'); END""",
    """CREATE TRIGGER immutable_submissions_update BEFORE UPDATE ON submissions
        BEGIN SELECT RAISE(ABORT, 'immutable submission'); END""",
    """CREATE TRIGGER immutable_submissions_delete BEFORE DELETE ON submissions
        BEGIN SELECT RAISE(ABORT, 'immutable submission'); END""",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def database_path(explicit: str | None = None) -> Path:
    configured = explicit or os.environ.get("TRADING_LAB_ORCHESTRATOR_DB")
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise ValueError("Set --db or TRADING_LAB_ORCHESTRATOR_DB (LOCALAPPDATA missing)")
        base = Path(local)
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    return (base / "TradingLab/orchestration/orchestrator.sqlite3").resolve()


class Store:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._initialize(conn)
                if conn.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError("Orchestration migration has invalid foreign keys")
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    @staticmethod
    def _initialize(conn: sqlite3.Connection) -> None:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        app = conn.execute("PRAGMA application_id").fetchone()[0]
        tables = conn.execute("SELECT name FROM sqlite_master").fetchall()
        if not tables and version == 0 and app == 0:
            for statement in DDL:
                conn.execute(statement)
            conn.execute(f"PRAGMA application_id={APPLICATION_ID}")
            conn.execute("PRAGMA user_version=1")
            version, app = 1, APPLICATION_ID
        if app != APPLICATION_ID or version not in (1, 2, 3, 4, 5, 6, SCHEMA_VERSION):
            raise ValueError("Not an orchestration v1 database; refusing to modify it")
        if version == 1:
            migrate_v2(conn)
            version = 2
        if version == 2:
            migrate_v3(conn)
            version = 3
        if version == 3:
            migrate_v4(conn)
            version = 4
        if version == 4:
            from .audit_store import migrate_v5

            migrate_v5(conn)
            version = 5
        if version == 5:
            from .circuit_store import migrate_v6

            migrate_v6(conn)
            version = 6
        if version == 6:
            from .process_identity import migrate_v7

            migrate_v7(conn)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=FULL")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    @staticmethod
    def _event(
        conn: sqlite3.Connection,
        candidate: str,
        task: str | None,
        entity: str,
        old: str | None,
        new: str,
        reason: str,
        payload: dict,
        actor: str = "manual_cli",
    ) -> None:
        encoded = canonical(payload)
        conn.execute(
            """INSERT INTO events(candidate_id, task_id, entity, old_state, new_state,
               actor, reason, created_at_utc, payload_json, payload_sha256)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (candidate, task, entity, old, new, actor, reason, utc_now(), encoded, digest(encoded)),
        )

    def register(self, manifest: HypothesisManifest) -> dict:
        with self.transaction() as conn:
            return self._register(conn, manifest)

    def _register(self, conn: sqlite3.Connection, manifest: HypothesisManifest) -> dict:
        # Revalidate even API callers; never trust model_construct or mutated nested containers.
        manifest = HypothesisManifest.model_validate_json(manifest.snapshot())
        snapshot = manifest.snapshot()
        sha = digest(snapshot)
        fingerprint = manifest.fingerprint()
        submitted = conn.execute(
            "SELECT * FROM submissions WHERE hypothesis_id=?", (manifest.hypothesis_id,)
        ).fetchone()
        if submitted and submitted["manifest_sha256"] != sha:
            raise ValueError("hypothesis_id already exists with different content; use a new ID")
        existing = conn.execute(
            "SELECT * FROM candidates WHERE fingerprint=?", (fingerprint,)
        ).fetchone()
        if existing:
            candidate = existing["candidate_id"]
            task = conn.execute(
                "SELECT task_id FROM tasks WHERE candidate_id=?", (candidate,)
            ).fetchone()[0]
            if not submitted:
                conn.execute(
                    "INSERT INTO submissions VALUES (?,?,?,?,?)",
                    (manifest.hypothesis_id, candidate, snapshot, sha, utc_now()),
                )
            # Retain every accepted attempt, including alternate IDs, without another task.
            self._event(
                conn,
                candidate,
                task,
                "submission",
                None,
                "DUPLICATE",
                "Exact ID/content or scientific fingerprint already registered",
                {"hypothesis_id": manifest.hypothesis_id, "manifest_sha256": sha},
            )
            return {
                "created": False,
                "candidate_id": candidate,
                "task_id": task,
                "status": existing["status"],
                "duplicate": True,
            }
        candidate, task = "cand_" + uuid4().hex, "task_" + uuid4().hex
        now = utc_now()
        conn.execute(
            "INSERT INTO candidates VALUES (?,?,?,?,?,'HYPOTHESIS_READY',?,?)",
            (candidate, manifest.hypothesis_id, fingerprint, snapshot, sha, now, now),
        )
        conn.execute(
            "INSERT INTO tasks VALUES (?,?,?,'MANUAL_REVIEW','PREPARE_ONLY','QUEUED',?,?)",
            (task, candidate, candidate + ":manual_review:v1", now, now),
        )
        conn.execute(
            "INSERT INTO submissions VALUES (?,?,?,?,?)",
            (manifest.hypothesis_id, candidate, snapshot, sha, now),
        )
        self._event(
            conn,
            candidate,
            None,
            "candidate",
            None,
            "IDEA_RECEIVED",
            "Manual manifest received",
            {"manifest_sha256": sha},
        )
        self._event(
            conn,
            candidate,
            None,
            "candidate",
            "IDEA_RECEIVED",
            "HYPOTHESIS_READY",
            "Contract v1.0 validated; review pending",
            {"fingerprint": fingerprint},
        )
        self._event(
            conn, candidate, task, "task", None, "QUEUED", "Manual review only; no worker", {}
        )
        return {
            "created": True,
            "candidate_id": candidate,
            "task_id": task,
            "status": "HYPOTHESIS_READY",
            "duplicate": False,
        }

    def list_candidates(self) -> list[dict]:
        with self.connection() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    """SELECT c.candidate_id,c.hypothesis_id,c.status,c.created_at_utc,
                   t.task_id,t.status AS task_status FROM candidates c
                   JOIN tasks t USING(candidate_id) ORDER BY c.created_at_utc,c.candidate_id"""
                )
            ]

    def show(self, identifier: str) -> dict:
        with self.connection() as conn:
            if not conn.in_transaction:
                conn.execute("BEGIN")  # Reuse an enclosing read snapshot when provided.
            rows = conn.execute(
                """SELECT c.* FROM candidates c JOIN tasks t USING(candidate_id)
                   WHERE c.candidate_id=? OR t.task_id=? OR EXISTS
                   (SELECT 1 FROM submissions s WHERE s.candidate_id=c.candidate_id
                    AND s.hypothesis_id=?)""",
                (identifier, identifier, identifier),
            ).fetchall()
            if len(rows) != 1:
                raise ValueError(f"Unknown or ambiguous candidate/task/hypothesis: {identifier}")
            result = dict(rows[0])
            candidate = result["candidate_id"]
            result["manifest"] = json.loads(result.pop("manifest_json"))
            result["task"] = dict(
                conn.execute("SELECT * FROM tasks WHERE candidate_id=?", (candidate,)).fetchone()
            )
            result["events"] = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM events WHERE candidate_id=? ORDER BY event_id", (candidate,)
                )
            ]
            result["submissions"] = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM submissions WHERE candidate_id=? "
                    "ORDER BY created_at_utc,hypothesis_id",
                    (candidate,),
                )
            ]
            result["attempts"] = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM attempts WHERE task_id=? ORDER BY number",
                    (result["task"]["task_id"],),
                )
            ]
            result["executions"] = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM executions WHERE task_id=? ORDER BY created_at_utc",
                    (result["task"]["task_id"],),
                )
            ]
            result["manual_repairs"] = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM manual_repairs WHERE task_id=? ORDER BY created_at_utc",
                    (result["task"]["task_id"],),
                )
            ]
            return result

    def transition(self, candidate: str, expected: str, target: str, reason: str) -> dict:
        if not reason.strip():
            raise ValueError("A non-empty reason is required")
        if target not in TRANSITIONS.get(expected, set()):
            raise ValueError(f"Transition not allowed in step 4.1: {expected} -> {target}")
        with self.transaction() as conn:
            active = conn.execute(
                """SELECT 1 FROM attempts a JOIN tasks t USING(task_id)
                WHERE t.candidate_id=? AND a.status IN ('PREPARED','RUNNING','UNKNOWN')""",
                (candidate,),
            ).fetchone()
            if active:
                raise ValueError("Implementation active or uncertain; reconcile its attempt first")
            row = conn.execute(
                "SELECT status FROM candidates WHERE candidate_id=?", (candidate,)
            ).fetchone()
            if not row or row[0] != expected:
                raise ValueError("Candidate absent or stale expected state; query before retrying")
            task = conn.execute("SELECT * FROM tasks WHERE candidate_id=?", (candidate,)).fetchone()
            now = utc_now()
            conn.execute(
                "UPDATE candidates SET status=?,updated_at_utc=? WHERE candidate_id=?",
                (target, now, candidate),
            )
            conn.execute(
                "UPDATE tasks SET status=?,updated_at_utc=? WHERE task_id=?",
                (TASK_STATE[target], now, task["task_id"]),
            )
            self._event(conn, candidate, None, "candidate", expected, target, reason, {})
            if task["status"] != TASK_STATE[target]:
                self._event(
                    conn,
                    candidate,
                    task["task_id"],
                    "task",
                    task["status"],
                    TASK_STATE[target],
                    reason,
                    {},
                )
        return {"candidate_id": candidate, "status": target, "task_status": TASK_STATE[target]}
