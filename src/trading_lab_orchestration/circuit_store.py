"""Only the durable links/checkpoint required by the manual 4.6 circuit."""


def migrate_v6(conn):
    conn.execute("""CREATE TABLE circuits (
        circuit_id TEXT PRIMARY KEY, request_sha256 TEXT NOT NULL,
        request_json TEXT NOT NULL, repo TEXT NOT NULL, base_commit TEXT NOT NULL,
        root TEXT NOT NULL UNIQUE, command_json TEXT NOT NULL,
        simulated INTEGER NOT NULL CHECK(simulated IN (0,1)),
        task_id TEXT UNIQUE REFERENCES tasks(task_id),
        attempt_id TEXT REFERENCES attempts(attempt_id),
        execution_id TEXT REFERENCES executions(execution_id),
        audit_id TEXT REFERENCES audits(audit_id),
        notification_id TEXT REFERENCES audit_outbox(notification_id),
        status TEXT NOT NULL CHECK(status IN
        ('PREPARED','RUNNING','BLOCKED','UNCERTAIN','NOTICE_PREPARED')),
        active_stage TEXT, error TEXT, evidence_json TEXT NOT NULL DEFAULT '{}',
        created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL)""")
    conn.execute("""CREATE TRIGGER immutable_circuit_request BEFORE UPDATE OF
        circuit_id,request_sha256,request_json,repo,base_commit,root,command_json,simulated,
        created_at_utc ON circuits
        BEGIN SELECT RAISE(ABORT,'immutable circuit request'); END""")
    conn.execute("PRAGMA user_version=6")
