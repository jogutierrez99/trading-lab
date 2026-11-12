"""Step 4.4 coordinator persistence. Never opens an experiment ledger for writing."""


def migrate_v5(conn):
    for sql in (
        """CREATE TABLE audits (
        audit_id TEXT PRIMARY KEY, execution_id TEXT NOT NULL REFERENCES executions(execution_id),
        intent_sha256 TEXT NOT NULL UNIQUE, request_json TEXT NOT NULL,
        root TEXT NOT NULL UNIQUE, status TEXT NOT NULL CHECK(status IN
        ('PREPARED','COMPLETED_WITH_LIMITATIONS','BLOCKED_EVIDENCE','FAILED')),
        verdict_sha256 TEXT, report_sha256 TEXT, created_at_utc TEXT NOT NULL)""",
        """CREATE TABLE audit_outbox (
        notification_id TEXT PRIMARY KEY, audit_id TEXT NOT NULL UNIQUE REFERENCES audits(audit_id),
        event TEXT NOT NULL CHECK(event='AUDIT_TECHNICAL_NOTICE'),
        recipient_sha256 TEXT, message TEXT NOT NULL, message_sha256 TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN
        ('DRAFT','SENDING','ACCEPTED','RETRYABLE','FAILED','UNKNOWN')),
        attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),
        message_id INTEGER, retry_after_utc REAL, outcome TEXT,
        created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL)""",
        """CREATE TABLE api_months (
        month TEXT PRIMARY KEY, opening_spend_cents INTEGER NOT NULL CHECK(opening_spend_cents>=0),
        reconciliation_note TEXT NOT NULL, created_at_utc TEXT NOT NULL)""",
        """CREATE TABLE api_calls (
        call_id TEXT PRIMARY KEY, month TEXT NOT NULL REFERENCES api_months(month),
        provider TEXT NOT NULL, purpose TEXT NOT NULL, reserved_cents INTEGER NOT NULL
        CHECK(reserved_cents>0), actual_cents INTEGER CHECK(actual_cents>=0),
        status TEXT NOT NULL CHECK(status IN ('RESERVED','SETTLED','UNKNOWN')),
        provenance TEXT, created_at_utc TEXT NOT NULL)""",
        """CREATE TRIGGER immutable_audit_identity BEFORE UPDATE OF audit_id, execution_id,
        intent_sha256, request_json, root, created_at_utc ON audits
        BEGIN SELECT RAISE(ABORT, 'immutable audit identity'); END""",
        """CREATE TRIGGER immutable_final_audit BEFORE UPDATE ON audits
        WHEN OLD.status != 'PREPARED'
        BEGIN SELECT RAISE(ABORT, 'immutable audit result'); END""",
    ):
        conn.execute(sql)
    conn.execute("PRAGMA user_version=5")
