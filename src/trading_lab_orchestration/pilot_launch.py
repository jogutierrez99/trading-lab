"""Independent, one-shot Codex launch approval for a prepared technical pilot."""

import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from .contracts import Identifier, canonical, digest
from .github_review import DEFAULT_AUTHOR_ID, _proposal
from .implementation_contracts import Hash
from .pilot_authorization import (
    LAUNCH_BLOCKED,
    PreparationAuthorization,
    authorization,
    authorization_for_attempt,
    budget_guard,
    check_disabled_profile,
    check_live_issue,
    current_operator,
    ledger_at_base,
)
from .process_identity import identity_state
from .processes import coordinator_lock
from .readonly import ReadOnlyStore
from .store import Store
from .verification_container import VerificationContainer
from .workspaces import changes, git


class LaunchAuthorization(PreparationAuthorization):
    permission: Literal["LAUNCH_CODEX"]
    attempt_id: Identifier
    preparation_authorization_id: Identifier
    preparation_sha256: Hash
    request_sha256: Hash
    controls_sha256: Hash
    verification_sha256: Hash
    max_invocations: Literal[1] = 1
    repair_allowed: Literal[False] = False
    okx_allowed: Literal[False] = False
    sandbox: Literal["workspace-write"] = "workspace-write"


@dataclass(frozen=True)
class PilotLaunch:
    authorization_id: str
    env_file: Path | None


DDL = (
    """CREATE TABLE IF NOT EXISTS pilot_launch_authorizations (
        authorization_id TEXT PRIMARY KEY,
        attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id),
        preparation_id TEXT NOT NULL REFERENCES pilot_authorizations(authorization_id),
        receipt_json TEXT NOT NULL, receipt_sha256 TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN
            ('APPROVED','RESERVED','CONSUMED','UNKNOWN','CLOSED','REVOKED'))
    )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS one_launch_authorization_per_attempt
        ON pilot_launch_authorizations(attempt_id) WHERE state!='REVOKED'""",
    """CREATE TRIGGER IF NOT EXISTS immutable_pilot_launch
        BEFORE UPDATE OF authorization_id,attempt_id,preparation_id,receipt_json,receipt_sha256
        ON pilot_launch_authorizations
        BEGIN SELECT RAISE(ABORT, 'immutable launch authorization'); END""",
    """CREATE TRIGGER IF NOT EXISTS preserve_pilot_launch
        BEFORE DELETE ON pilot_launch_authorizations
        BEGIN SELECT RAISE(ABORT, 'immutable launch authorization'); END""",
    """CREATE TRIGGER IF NOT EXISTS no_replace_pilot_launch
        BEFORE INSERT ON pilot_launch_authorizations WHEN EXISTS(
            SELECT 1 FROM pilot_launch_authorizations WHERE authorization_id=NEW.authorization_id
            OR (attempt_id=NEW.attempt_id AND state!='REVOKED' AND NEW.state!='REVOKED')
        ) BEGIN SELECT RAISE(ABORT, 'launch authorization already exists'); END""",
    """CREATE TRIGGER IF NOT EXISTS no_replace_pilot_preparation
        BEFORE INSERT ON pilot_authorizations WHEN EXISTS(
            SELECT 1 FROM pilot_authorizations WHERE authorization_id=NEW.authorization_id
            OR attempt_id=NEW.attempt_id
            OR (task_id=NEW.task_id AND state!='REVOKED' AND NEW.state!='REVOKED')
        ) BEGIN SELECT RAISE(ABORT, 'technical pilot authorization already exists'); END""",
    """CREATE TRIGGER IF NOT EXISTS pilot_launch_transition
        BEFORE UPDATE OF state ON pilot_launch_authorizations WHEN NOT (
            (OLD.state='APPROVED' AND NEW.state IN ('RESERVED','REVOKED'))
            OR (OLD.state='RESERVED' AND NEW.state IN ('CONSUMED','UNKNOWN','CLOSED'))
            OR (OLD.state='UNKNOWN' AND NEW.state='CLOSED')
        ) BEGIN SELECT RAISE(ABORT, 'invalid launch authorization transition'); END""",
    """CREATE TRIGGER IF NOT EXISTS pilot_launch_reservation_event
        BEFORE UPDATE OF state ON pilot_launch_authorizations
        WHEN NEW.state='RESERVED' AND NOT EXISTS(
            SELECT 1 FROM events e JOIN attempts a ON a.task_id=e.task_id
            WHERE a.attempt_id=OLD.attempt_id AND a.status='PREPARED'
            AND e.new_state='LAUNCH_RESERVED' AND e.old_state='LAUNCH_APPROVED'
            AND json_extract(e.payload_json,'$.authorization_id')=OLD.authorization_id
            AND json_extract(e.payload_json,'$.attempt_id')=OLD.attempt_id
            AND json_extract(e.payload_json,'$.receipt_sha256')=OLD.receipt_sha256
        ) BEGIN SELECT RAISE(ABORT, 'launch reservation requires its audit event'); END""",
    """CREATE TRIGGER IF NOT EXISTS pilot_launch_sealed_attempt
        BEFORE UPDATE OF attempt_id,task_id,number,base_commit,repo,root,workspace,branch,
            request_sha256,controls_sha256 ON attempts
        WHEN EXISTS(SELECT 1 FROM pilot_launch_authorizations WHERE attempt_id=OLD.attempt_id)
        BEGIN SELECT RAISE(ABORT, 'sealed launch attempt'); END""",
    """CREATE TRIGGER IF NOT EXISTS no_replace_pilot_launch_attempt
        BEFORE INSERT ON attempts WHEN EXISTS(
            SELECT 1 FROM pilot_launch_authorizations l JOIN attempts a USING(attempt_id)
            WHERE a.attempt_id=NEW.attempt_id OR (a.task_id=NEW.task_id AND a.number=NEW.number)
        ) BEGIN SELECT RAISE(ABORT, 'sealed launch attempt'); END""",
    """CREATE TRIGGER IF NOT EXISTS pilot_launch_no_backtest
        BEFORE INSERT ON executions WHEN EXISTS(
            SELECT 1 FROM pilot_authorizations WHERE attempt_id=NEW.attempt_id
        ) BEGIN SELECT RAISE(ABORT, 'technical pilot requires separate backtest authorization');
        END""",
)

# Installed in the same transaction as the first explicit launch approval.
# Existing PREPARE_ONLY databases retain their stricter trigger until then.
LAUNCH_TRIGGER = """CREATE TRIGGER pilot_attempt_no_launch
    BEFORE UPDATE OF status,retry_allowed ON attempts
    WHEN EXISTS(SELECT 1 FROM pilot_authorizations p WHERE p.attempt_id=OLD.attempt_id)
    AND (NEW.retry_allowed!=0
        OR (NEW.status IN ('RUNNING','SUCCEEDED') AND NOT EXISTS(
            SELECT 1 FROM pilot_launch_authorizations l
            JOIN pilot_authorizations p ON p.authorization_id=l.preparation_id
            WHERE l.attempt_id=OLD.attempt_id AND p.attempt_id=OLD.attempt_id
                AND l.state='RESERVED' AND p.state='CONSUMED'
                AND json_extract(l.receipt_json,'$.request_sha256')=OLD.request_sha256
                AND json_extract(l.receipt_json,'$.controls_sha256')=OLD.controls_sha256
                AND ((NEW.status='RUNNING' AND OLD.status='PREPARED')
                    OR (NEW.status='SUCCEEDED' AND OLD.status='RUNNING'))
        )))
    BEGIN SELECT RAISE(ABORT, 'technical pilot has no launch authorization'); END"""


def _has_table(conn):
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pilot_launch_authorizations'"
        ).fetchone()
        is not None
    )


def launch_for_attempt(conn, attempt_id):
    if _has_table(conn):
        return conn.execute(
            "SELECT * FROM pilot_launch_authorizations WHERE attempt_id=? AND state!='REVOKED'",
            (attempt_id,),
        ).fetchone()
    return None


def read_launch(conn, identifier):
    row = (
        conn.execute(
            "SELECT * FROM pilot_launch_authorizations WHERE authorization_id=?", (identifier,)
        ).fetchone()
        if _has_table(conn)
        else None
    )
    if not row:
        raise ValueError(LAUNCH_BLOCKED)
    receipt = LaunchAuthorization.model_validate_json(row["receipt_json"])
    if (
        digest(row["receipt_json"]) != row["receipt_sha256"]
        or receipt.attempt_id != row["attempt_id"]
        or receipt.preparation_authorization_id != row["preparation_id"]
    ):
        raise ValueError("Launch receipt integrity mismatch")
    return row, receipt


def prepared_scope(conn, coordinator, attempt):
    from .implementation import review_spec

    attempt_id = attempt["attempt_id"]
    prep = authorization_for_attempt(conn, attempt_id)
    if not prep or prep["state"] != "CONSUMED":
        raise ValueError("Launch requires consumed preparation for this attempt")
    prep, original = authorization(conn, prep["authorization_id"])
    if (
        attempt["status"] != "PREPARED"
        or attempt["started_at_utc"] is not None
        or attempt["number"] != 1
        or attempt["retry_allowed"]
        or attempt["task_id"] != original.task_id
        or attempt["base_commit"] != original.base_commit
        or attempt["process_state"] not in {"EXITED", "REUSED", "NOT_RECORDED"}
    ):
        raise ValueError("Pilot is not an untouched first prepared attempt")
    checkpoint = conn.execute(
        "SELECT * FROM github_intake WHERE issue_number=?", (original.issue_number,)
    ).fetchone()
    if (
        not checkpoint
        or checkpoint["status"] != "ACCEPTED"
        or checkpoint["issue_id"] != original.issue_id
        or checkpoint["proposal_sha256"] != original.proposal_sha256
        or checkpoint["body_sha256"] != original.body_sha256
    ):
        raise ValueError("Launch checkpoint differs from the preparation receipt")
    proposal, task = _proposal(conn, checkpoint, original.task_id, DEFAULT_AUTHOR_ID)
    if (task["kind"], task["mode"], task["status"], task["candidate_status"]) != (
        "IMPLEMENTATION",
        "PREPARE_ONLY",
        "QUEUED",
        "DEVELOPMENT_QUEUED",
    ):
        raise ValueError("Pilot task changed after preparation")
    request = coordinator._request(attempt)
    if (
        request.attempt_id != attempt_id
        or request.task_id != original.task_id
        or request.candidate_id != task["candidate_id"]
        or request.attempt_number != 1
        or request.base_commit != original.base_commit
        or request.branch != attempt["branch"]
        or Path(request.workspace) != Path(attempt["workspace"])
        or request.hypothesis_manifest != proposal.manifest
        or request.hypothesis_sha256 != task["manifest_sha256"]
        or digest(canonical(request.plan.model_dump(mode="json"))) != original.plan_sha256
        or request.plan.operation != original.operation
        or request.allowed_write_paths != request.plan.paths()
        or request.authorized_checks != request.plan.checks()
        or request.plan.max_wall_seconds != original.max_wall_seconds
        or request.plan.check_timeout_seconds != original.check_timeout_seconds
        or request.previous_attempt is not None
        or request.native_interface_check != "SYNTHETIC_OHLCV_UTC_V1"
    ):
        raise ValueError("Prepared request differs from the authorized scope")
    review_spec(proposal.manifest, request.plan)
    root, workspace = Path(attempt["root"]), Path(attempt["workspace"])
    if (
        git(workspace, "rev-parse", "HEAD") != original.base_commit
        or git(workspace, "branch", "--show-current") != attempt["branch"]
        or git(workspace, "diff", "--cached", "--name-only")
    ):
        raise ValueError("Prepared worktree revision changed")
    expected = json.loads((root / "prepared-files.json").read_bytes())
    if set(expected) != set(request.allowed_write_paths) or changes(attempt) != expected:
        raise ValueError("Prepared workspace changed before launch")
    check_disabled_profile(workspace / request.plan.paths()[1])
    if any(
        (root / name).exists()
        for name in (
            "cli-probe.json",
            "codex.jsonl",
            "codex.stderr",
            "delivery.json",
            "process-result.json",
        )
    ):
        raise ValueError("Launch evidence already exists; do not relaunch")
    ledger = ledger_at_base(workspace, request.base_commit)
    if ledger != Path(original.ledger_path):
        raise ValueError("Canonical ledger differs from the preparation receipt")
    return prep, original, request, checkpoint, ledger


def binding(conn, coordinator, attempt, *, approved_at):
    prep, original, _, checkpoint, ledger = prepared_scope(conn, coordinator, attempt)
    account, sid = current_operator()
    receipt = LaunchAuthorization.model_validate_json(
        canonical(
            original.model_dump(mode="json")
            | {
                "permission": "LAUNCH_CODEX",
                "attempt_id": attempt["attempt_id"],
                "preparation_authorization_id": prep["authorization_id"],
                "preparation_sha256": prep["receipt_sha256"],
                "request_sha256": attempt["request_sha256"],
                "controls_sha256": attempt["controls_sha256"],
                "verification_sha256": VerificationContainer().fingerprint,
                "approved_by": account,
                "operator_sid": sid,
                "approved_at_utc": approved_at.isoformat(),
            }
        )
    )
    return receipt, checkpoint, ledger


def check_idle(conn, attempt_id):
    if (
        conn.execute(
            "SELECT 1 FROM attempts WHERE attempt_id!=? "
            "AND status IN ('PREPARED','RUNNING','UNKNOWN')",
            (attempt_id,),
        ).fetchone()
        or conn.execute(
            "SELECT 1 FROM executions WHERE status IN ('PREPARED','RUNNING','UNKNOWN')"
        ).fetchone()
        or conn.execute(
            "SELECT 1 FROM manual_repairs WHERE status IN ('RUNNING','UNKNOWN')"
        ).fetchone()
    ):
        raise ValueError("Another implementation, execution or repair is active or uncertain")


def _event(conn, row, receipt, before, after, reason):
    candidate = conn.execute(
        "SELECT candidate_id FROM tasks WHERE task_id=?", (receipt.task_id,)
    ).fetchone()[0]
    Store._event(
        conn,
        candidate,
        receipt.task_id,
        "task",
        f"LAUNCH_{before}" if before else None,
        f"LAUNCH_{after}",
        reason,
        {
            "authorization_id": row["authorization_id"],
            "attempt_id": receipt.attempt_id,
            "receipt_sha256": row["receipt_sha256"],
            "operator_sid": receipt.operator_sid,
        },
        actor=receipt.approved_by,
    )


def _persist_launch(conn, receipt):
    had_table = _has_table(conn)
    for statement in DDL:
        conn.execute(statement)
    if not had_table:
        conn.execute("DROP TRIGGER pilot_attempt_no_launch")
        conn.execute(LAUNCH_TRIGGER)
    encoded = canonical(receipt.model_dump(mode="json"))
    identifier = "pilot_launch_" + uuid4().hex
    row = {"authorization_id": identifier, "receipt_sha256": digest(encoded)}
    try:
        conn.execute(
            "INSERT INTO pilot_launch_authorizations VALUES (?,?,?,?,?,'APPROVED')",
            (
                identifier,
                receipt.attempt_id,
                receipt.preparation_authorization_id,
                encoded,
                row["receipt_sha256"],
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Launch authorization already exists for this attempt") from exc
    _event(conn, row, receipt, None, "APPROVED", "Independent interactive launch approval")
    return row | {"state": "APPROVED"}


def approve_launch(database, coordinator, attempt_id, env_file):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError("Launch approval requires an interactive Windows terminal")
    attempt = coordinator.attempt(attempt_id)
    with ReadOnlyStore(database).connection() as conn:
        receipt, checkpoint, ledger = binding(
            conn, coordinator, attempt, approved_at=datetime.now(UTC)
        )
    check_live_issue(checkpoint, env_file)
    if VerificationContainer().preflight()["verification_sha256"] != receipt.verification_sha256:
        raise ValueError("Verifier configuration changed before launch approval")
    print(json.dumps(receipt.model_dump(mode="json"), indent=2, ensure_ascii=True))
    challenge = f"LANZAR {attempt_id} {receipt.controls_sha256}"
    if input(f"Escribe exactamente {challenge}: ") != challenge:
        raise ValueError("Launch confirmation did not match")
    approved_at = datetime.now(UTC)
    with coordinator_lock(coordinator.lock), budget_guard(database, ledger):
        attempt = coordinator.attempt(attempt_id)
        with Store(database).transaction() as conn:
            check_idle(conn, attempt_id)
            actual, checkpoint, _ = binding(conn, coordinator, attempt, approved_at=approved_at)
            if actual != receipt.model_copy(update={"approved_at_utc": approved_at}):
                raise ValueError("Launch scope changed during confirmation")
            check_live_issue(checkpoint, env_file)
            return _persist_launch(conn, actual)


def transition(conn, row, receipt, state, reason):
    _event(conn, row, receipt, row["state"], state, reason)
    conn.execute(
        "UPDATE pilot_launch_authorizations SET state=? WHERE authorization_id=?",
        (state, row["authorization_id"]),
    )


def validate_launch(conn, coordinator, attempt, permit):
    row, approved = read_launch(conn, permit.authorization_id)
    if row["state"] != "APPROVED" or approved.attempt_id != attempt["attempt_id"]:
        raise ValueError("Launch authorization unavailable or belongs to another attempt")
    actual, checkpoint, ledger = binding(
        conn,
        coordinator,
        attempt,
        approved_at=approved.approved_at_utc,
    )
    if actual != approved or approved.approved_at_utc > datetime.now(UTC):
        raise ValueError("Launch receipt, operator or sealed scope changed")
    check_live_issue(checkpoint, permit.env_file)
    return row, approved, ledger


def finish_launch(conn, attempt_id, status, reason):
    row = launch_for_attempt(conn, attempt_id)
    if row and (row["state"] == "RESERVED" or status == "CANCELLED" and row["state"] == "UNKNOWN"):
        row, receipt = read_launch(conn, row["authorization_id"])
        state = {"UNKNOWN": "UNKNOWN", "CANCELLED": "CLOSED"}.get(status, "CONSUMED")
        transition(conn, row, receipt, state, reason)


def close_launch(coordinator, identifier, reason, *, confirm_stopped=False):
    if not reason.strip():
        raise ValueError("Explicit reconciliation reason required")
    with coordinator_lock(coordinator.lock):
        with coordinator.store.transaction() as conn:
            row, receipt = read_launch(conn, identifier)
            if (receipt.approved_by, receipt.operator_sid) != current_operator():
                raise ValueError("PILOT_OPERATOR_MISMATCH")
            if row["state"] == "APPROVED":
                transition(conn, row, receipt, "REVOKED", reason)
                return {"authorization_id": identifier, "state": "REVOKED"}
        if row["state"] not in {"RESERVED", "UNKNOWN"} or not confirm_stopped:
            raise ValueError("Reconciliation requires an uncertain launch and stopped confirmation")
        attempt = coordinator.attempt(receipt.attempt_id)
        if attempt["child_pid"] is not None and identity_state(
            attempt["child_pid"], attempt["process_identity_json"]
        ) not in {"EXITED", "REUSED"}:
            raise ValueError("Recorded process is active or unverified")
        for record in Path(attempt["root"]).glob("verification_*/check-*-container.json"):
            cleanup = record.with_name(record.name.replace("-container.json", "-cleanup.json"))
            if cleanup.exists():
                outcome = json.loads(cleanup.read_bytes())
                if VerificationContainer._ok(outcome):
                    continue
            verifier = VerificationContainer()
            if verifier.fingerprint != receipt.verification_sha256:
                raise ValueError("Restore the sealed verifier configuration before reconciliation")
            verifier.confirm_cleanup(json.loads(record.read_bytes())["container"])
        return coordinator._finish(receipt.attempt_id, "CANCELLED", reason)
