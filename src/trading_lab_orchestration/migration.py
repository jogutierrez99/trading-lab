"""Version 2: extend existing intake entities, add only implementation attempts."""

import sqlite3


def migrate_v2(conn: sqlite3.Connection) -> None:
    # Caller holds BEGIN IMMEDIATE with foreign_keys OFF; verify FKs before commit.
    for table, states in (
        (
            "candidates",
            "'IMPLEMENTING','IMPLEMENTATION_READY','DEVELOPMENT_QUEUED',"
            "'GATE_RESEARCH_APPROVED','FAILED'",
        ),
        ("tasks", "'RUNNING','SUCCEEDED','FAILED','TIMED_OUT'"),
    ):
        original = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()[0]
        old = "'ARCHIVED'" if table == "candidates" else "'CANCELLED'"
        revised = original.replace(f"CREATE TABLE {table}", f"CREATE TABLE {table}_new", 1)
        revised = revised.replace(old + "))", old + "," + states + "))")
        if table == "tasks":
            revised = revised.replace(
                "kind='MANUAL_REVIEW'", "kind IN ('MANUAL_REVIEW','IMPLEMENTATION')"
            )
        conn.execute(revised)
        conn.execute(f"INSERT INTO {table}_new SELECT * FROM {table}")
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
    conn.execute("""CREATE TRIGGER immutable_manifest BEFORE UPDATE OF candidate_id, hypothesis_id,
        fingerprint, manifest_json, manifest_sha256, created_at_utc ON candidates
        BEGIN SELECT RAISE(ABORT, 'immutable candidate snapshot'); END""")
    conn.execute("""CREATE TABLE attempts (
        attempt_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES tasks(task_id),
        number INTEGER NOT NULL CHECK(number BETWEEN 1 AND 3),
        status TEXT NOT NULL CHECK(status IN ('PREPARED','RUNNING','SUCCEEDED','FAILED',
            'BLOCKED','TIMED_OUT','UNKNOWN','CANCELLED')),
        repo TEXT NOT NULL, root TEXT NOT NULL, workspace TEXT NOT NULL,
        branch TEXT NOT NULL, base_commit TEXT NOT NULL,
        request_sha256 TEXT, controls_sha256 TEXT,
        created_at_utc TEXT NOT NULL, started_at_utc TEXT, ended_at_utc TEXT,
        child_pid INTEGER, error TEXT, retry_allowed INTEGER NOT NULL DEFAULT 0,
        UNIQUE(task_id,number))""")
    conn.execute("""CREATE UNIQUE INDEX one_active_implementation ON attempts((1))
        WHERE status IN ('PREPARED','RUNNING','UNKNOWN')""")
    conn.execute("PRAGMA user_version=2")


def migrate_v3(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE executions (
        execution_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES tasks(task_id),
        attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
        intent_sha256 TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('PREPARED','RUNNING','UNKNOWN',
            'SUCCEEDED','FAILED','TIMED_OUT','BLOCKED','CANCELLED')),
        root TEXT NOT NULL UNIQUE, request_sha256 TEXT, seal_sha256 TEXT,
        created_at_utc TEXT NOT NULL, started_at_utc TEXT, ended_at_utc TEXT,
        child_pid INTEGER, error TEXT, retry_of TEXT REFERENCES executions(execution_id))""")
    conn.execute("""CREATE UNIQUE INDEX one_heavy_execution ON executions((1))
        WHERE status IN ('PREPARED','RUNNING','UNKNOWN')""")
    conn.execute("PRAGMA user_version=3")


def migrate_v4(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE manual_repairs (
        repair_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES tasks(task_id),
        source_attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
        operation TEXT NOT NULL CHECK(operation='PILOT_UTC_INDEX_COMPATIBILITY_V1'),
        status TEXT NOT NULL CHECK(status IN
            ('RUNNING','UNKNOWN','SUCCEEDED','FAILED','CANCELLED')),
        root TEXT NOT NULL UNIQUE, request_sha256 TEXT, seal_sha256 TEXT,
        receipt_path TEXT, receipt_sha256 TEXT, artifacts_sha256 TEXT,
        created_at_utc TEXT NOT NULL, ended_at_utc TEXT, child_pid INTEGER, error TEXT,
        UNIQUE(source_attempt_id,operation))""")
    conn.execute("""CREATE UNIQUE INDEX one_active_manual_repair ON manual_repairs((1))
        WHERE status IN ('RUNNING','UNKNOWN')""")
    conn.execute(
        "ALTER TABLE executions ADD COLUMN manual_repair_id TEXT "
        "REFERENCES manual_repairs(repair_id)"
    )
    conn.execute("""CREATE TRIGGER execution_manual_source BEFORE INSERT ON executions
        WHEN NEW.manual_repair_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM manual_repairs r WHERE r.repair_id=NEW.manual_repair_id
            AND r.source_attempt_id=NEW.attempt_id AND r.task_id=NEW.task_id
            AND r.status='SUCCEEDED')
        BEGIN SELECT RAISE(ABORT,'manual implementation source mismatch'); END""")
    conn.execute("PRAGMA user_version=4")
