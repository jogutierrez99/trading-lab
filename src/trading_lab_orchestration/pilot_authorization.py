"""One-shot local approval for a sealed GitHub technical pilot."""

import csv
import ctypes
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field

from .audit_model import Budget
from .contracts import canonical, digest
from .github_intake import LABEL, REPO, fetch_issue, parse_proposal, read_token
from .github_review import DEFAULT_AUTHOR_ID, ReviewAuthorization, _proposal
from .implementation_contracts import TECHNICAL_PILOT_ORIGIN, Hash, ImplementationPlan
from .processes import coordinator_lock
from .readonly import ReadOnlyStore
from .store import Store
from .workspaces import git

LAUNCH_BLOCKED = "TECHNICAL_PILOT_LAUNCH_AUTHORIZATION_NOT_ENABLED"
ISSUE_3_BASE = "703829cf19f5b8321b78a2b51949a5db7aa7d380"
ISSUE_3_TASK = "task_49117ca728ca460f80adf178a99e4b97"
PILOT_FILES = "examples/orchestration/phase-5-4b"

DDL = (
    """CREATE TABLE IF NOT EXISTS pilot_authorizations (
        authorization_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES tasks(task_id),
        receipt_json TEXT NOT NULL, receipt_sha256 TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN
            ('APPROVED','RESERVED','CONSUMED','UNKNOWN','CLOSED','REVOKED')),
        attempt_id TEXT UNIQUE REFERENCES attempts(attempt_id)
    )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS one_pilot_authorization_per_task
        ON pilot_authorizations(task_id) WHERE state != 'REVOKED'""",
    """CREATE TRIGGER IF NOT EXISTS immutable_pilot_authorization
        BEFORE UPDATE OF authorization_id,task_id,receipt_json,receipt_sha256
        ON pilot_authorizations BEGIN SELECT RAISE(ABORT, 'immutable authorization'); END""",
    """CREATE TRIGGER IF NOT EXISTS preserve_pilot_authorization
        BEFORE DELETE ON pilot_authorizations
        BEGIN SELECT RAISE(ABORT, 'immutable authorization'); END""",
    """CREATE TRIGGER IF NOT EXISTS pilot_authorization_transition
        BEFORE UPDATE OF state,attempt_id ON pilot_authorizations
        WHEN NOT (
            (OLD.state='APPROVED' AND NEW.state='RESERVED' AND NEW.attempt_id IS NOT NULL)
            OR (OLD.state='APPROVED' AND NEW.state='REVOKED' AND NEW.attempt_id IS NULL)
            OR (OLD.attempt_id IS NOT NULL AND NEW.attempt_id=OLD.attempt_id AND (
                (OLD.state='RESERVED' AND NEW.state IN ('CONSUMED','UNKNOWN','CLOSED'))
                OR (OLD.state IN ('UNKNOWN','CONSUMED') AND NEW.state='CLOSED')))
        ) BEGIN SELECT RAISE(ABORT, 'invalid authorization transition'); END""",
    """CREATE TRIGGER IF NOT EXISTS pilot_attempt_no_launch
        BEFORE UPDATE OF status,retry_allowed ON attempts
        WHEN (NEW.status IN ('RUNNING','SUCCEEDED') OR NEW.retry_allowed!=0)
            AND EXISTS(SELECT 1 FROM pilot_authorizations WHERE attempt_id=OLD.attempt_id)
        BEGIN SELECT RAISE(ABORT, 'technical pilot has no launch authorization'); END""",
)


class PreparationAuthorization(ReviewAuthorization):
    operation: Literal["NEW_STRATEGY"]
    base_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    body_sha256: Hash
    operator_sid: str = Field(pattern=r"^S-1-(?:[0-9]+-)*[0-9]+$")
    ledger_path: str
    max_attempts: Literal[1] = 1
    max_wall_seconds: int = Field(ge=1, le=600)
    check_timeout_seconds: int = Field(ge=1, le=60)
    max_api_eur: Literal[0] = 0
    backtests_allowed: Literal[False] = False


@dataclass(frozen=True)
class PilotPreparation:
    authorization_id: str
    env_file: Path | None


def current_operator() -> tuple[str, str]:
    if os.name != "nt":
        raise ValueError("Technical pilot approval requires a Windows process identity")
    try:
        system_dir = ctypes.create_unicode_buffer(32768)
        count = ctypes.windll.kernel32.GetSystemDirectoryW(system_dir, len(system_dir))
        if not 0 < count < len(system_dir):
            raise ValueError("Windows system directory could not be verified")
        result = subprocess.run(
            [
                str(Path(system_dir.value) / "whoami.exe"),
                "/user",
                "/fo",
                "csv",
                "/nh",
            ],
            capture_output=True,
            check=True,
            timeout=5,
            text=True,
            encoding="oem",
        )
        ((account, sid),) = csv.reader(result.stdout.strip().splitlines())
        if not account or not sid.startswith("S-1-"):
            raise ValueError("Invalid Windows token identity")
        return account.casefold(), sid
    except (OSError, KeyError, ValueError, subprocess.SubprocessError) as exc:
        raise ValueError("Windows process identity could not be verified") from exc


def _has_table(conn):
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pilot_authorizations'"
        ).fetchone()
        is not None
    )


def authorization(conn, authorization_id):
    row = (
        conn.execute(
            "SELECT * FROM pilot_authorizations WHERE authorization_id=?", (authorization_id,)
        ).fetchone()
        if _has_table(conn)
        else None
    )
    if not row:
        raise ValueError("PILOT_AUTHORIZATION_REQUIRED")
    if digest(row["receipt_json"]) != row["receipt_sha256"]:
        raise ValueError("PILOT_AUTHORIZATION_HASH_MISMATCH")
    receipt = PreparationAuthorization.model_validate_json(row["receipt_json"])
    if receipt.task_id != row["task_id"]:
        raise ValueError("PILOT_AUTHORIZATION_TASK_MISMATCH")
    return row, receipt


def authorization_for_attempt(conn, attempt_id):
    return (
        _has_table(conn)
        and conn.execute(
            "SELECT * FROM pilot_authorizations WHERE attempt_id=?", (attempt_id,)
        ).fetchone()
    )


def _subject(conn, issue_number, task_id):
    row = conn.execute(
        "SELECT * FROM github_intake WHERE issue_number=?", (issue_number,)
    ).fetchone()
    if not row or row["status"] != "ACCEPTED":
        raise ValueError("Accepted GitHub checkpoint required")
    proposal, task = _proposal(conn, row, task_id, DEFAULT_AUTHOR_ID)
    if proposal.origin != TECHNICAL_PILOT_ORIGIN:
        raise ValueError("Authorization requires supervised technical provenance")
    if conn.execute("SELECT 1 FROM attempts WHERE task_id=?", (task_id,)).fetchone():
        raise ValueError("Technical pilot already has an attempt")
    if (task["kind"], task["mode"], task["status"], task["candidate_status"]) != (
        "MANUAL_REVIEW",
        "PREPARE_ONLY",
        "QUEUED",
        "HYPOTHESIS_READY",
    ):
        raise ValueError("Pilot requires a queued manual review")
    return row, proposal


def ledger_at_base(repo, base):
    config = json.loads(
        git(repo, "show", f"{base}:examples/orchestration/flow1_billing_worker.json")
    )
    location = config.get("ledger") if isinstance(config, dict) else None
    if not isinstance(location, str) or not Path(location).is_absolute():
        raise ValueError("The approved base must pin an absolute canonical ledger path")
    return Path(location).resolve()


def validate_binding(conn, receipt, plan, repo, base, ledger):
    row, proposal = _subject(conn, receipt.issue_number, receipt.task_id)
    if (
        receipt.approved_by,
        receipt.operator_sid,
    ) != current_operator() or receipt.approved_at_utc > datetime.now(UTC):
        raise ValueError("PILOT_OPERATOR_MISMATCH")
    if (
        receipt.issue_id != row["issue_id"]
        or receipt.proposal_sha256 != row["proposal_sha256"]
        or receipt.body_sha256 != row["body_sha256"]
        or receipt.plan_sha256 != digest(canonical(plan.model_dump(mode="json")))
        or receipt.base_commit != base
        or Path(receipt.ledger_path) != ledger.resolve()
        or plan.target != proposal.manifest.hypothesis_id
        or plan.operation != receipt.operation
        or plan.max_wall_seconds != receipt.max_wall_seconds
        or plan.check_timeout_seconds != receipt.check_timeout_seconds
    ):
        raise ValueError("PILOT_AUTHORIZATION_BINDING_MISMATCH")
    if row["issue_id"] == 6429388150:
        if receipt.task_id != ISSUE_3_TASK:
            raise ValueError("Issue #3 requires its original queued task")
        if base != ISSUE_3_BASE:
            raise ValueError("Issue #3 requires its reviewed base commit")
        frozen = parse_proposal(git(repo, "show", f"{base}:{PILOT_FILES}/issue-body.json"))
        frozen_plan = ImplementationPlan.model_validate_json(
            git(repo, "show", f"{base}:{PILOT_FILES}/implementation-plan.draft.json")
        )
        if frozen != proposal or frozen_plan != plan:
            raise ValueError("Issue #3 requires its proposal and plan frozen at the reviewed base")
    if ledger_at_base(repo, base) != ledger.resolve():
        raise ValueError("Ledger differs from the canonical path in the approved base")
    if git(repo, "remote", "get-url", "origin") not in {
        f"git@github.com:{REPO}.git",
        f"https://github.com/{REPO}.git",
    }:
        raise ValueError("Pilot repository origin differs from the approved repository")
    from .implementation import review_spec

    review_spec(proposal.manifest, plan)
    return row


def check_live_issue(checkpoint, env_file):
    issue = fetch_issue(read_token(env_file), checkpoint["issue_number"])[0]
    if not isinstance(issue, dict):
        raise ValueError("Live Issue is unavailable")
    body = issue.get("body")
    author = issue.get("user")
    labels = issue.get("labels")
    if (
        issue.get("number") != checkpoint["issue_number"]
        or issue.get("id") != checkpoint["issue_id"]
        or issue.get("state") != "open"
        or issue.get("html_url") != checkpoint["issue_url"]
        or not isinstance(author, dict)
        or author.get("id") != checkpoint["author_id"]
        or "pull_request" in issue
        or not isinstance(labels, list)
        or not any(isinstance(label, dict) and label.get("name") == LABEL for label in labels)
        or not isinstance(body, str)
        or digest(body) != checkpoint["body_sha256"]
    ):
        raise ValueError("Live Issue differs from the approved checkpoint")


def check_disabled_profile(path):
    from quant_lab.config import StrategyConfig, load_yaml

    profile = load_yaml(path, StrategyConfig)
    if profile.enabled is not False or "enabled" not in profile.model_fields_set:
        raise ValueError("Prepared pilot profile must remain disabled")


@contextmanager
def budget_guard(queue_path, ledger):
    if queue_path.resolve() == ledger.resolve():
        raise ValueError("Use the separate canonical API ledger")
    store = ReadOnlyStore(ledger)
    with store.snapshot(), store.connection() as conn:
        # A rollback-journal read lock spans the queue commit. WAL allows concurrent commits.
        if conn.execute("PRAGMA journal_mode").fetchone()[0] not in {
            "delete",
            "truncate",
            "persist",
        }:
            raise ValueError("Cannot hold a stable billing check with this ledger journal mode")
        if Budget(store).available() <= 0:
            raise ValueError("GLOBAL_API_BUDGET_EXHAUSTED")
        yield


def _event(conn, receipt, auth_id, before, after, reason, attempt_id=None):
    candidate = conn.execute(
        "SELECT candidate_id FROM tasks WHERE task_id=?", (receipt.task_id,)
    ).fetchone()[0]
    Store._event(
        conn,
        candidate,
        receipt.task_id,
        "task",
        f"AUTH_{before}" if before else None,
        f"AUTH_{after}",
        reason,
        {
            "authorization_id": auth_id,
            "attempt_id": attempt_id,
            "operator_sid": receipt.operator_sid,
        },
        actor=receipt.approved_by,
    )


def approve_authorization(database, receipt, plan, repo, ledger, env_file):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError("Approval requires an interactive Windows terminal")
    with ReadOnlyStore(database).connection() as conn:
        row = validate_binding(conn, receipt, plan, repo, git(repo, "rev-parse", "HEAD"), ledger)
    check_live_issue(row, env_file)
    display = receipt.model_dump(mode="json")
    display.pop("approved_at_utc")
    print(json.dumps(display | {"paths": plan.paths()}, indent=2, ensure_ascii=True))
    challenge = f"AUTORIZAR {receipt.task_id} {receipt.base_commit}"
    if input(f"Escribe exactamente {challenge} para aprobar solo la preparacion: ") != challenge:
        raise ValueError("Approval confirmation did not match")
    receipt = PreparationAuthorization.model_validate_json(
        canonical(display | {"approved_at_utc": datetime.now(UTC).isoformat()})
    )
    with (
        coordinator_lock(database.with_suffix(".implementation.lock")),
        budget_guard(database, ledger),
        Store(database).transaction() as conn,
    ):
        return _persist_authorization(conn, receipt, plan, repo, ledger)


def _persist_authorization(conn, receipt, plan, repo, ledger):
    receipt = PreparationAuthorization.model_validate_json(
        canonical(receipt.model_dump(mode="json"))
    )
    validate_binding(conn, receipt, plan, repo, git(repo, "rev-parse", "HEAD"), ledger)
    for statement in DDL:
        conn.execute(statement)
    auth_id = "pilot_auth_" + uuid4().hex
    encoded = canonical(receipt.model_dump(mode="json"))
    try:
        conn.execute(
            "INSERT INTO pilot_authorizations VALUES (?,?,?,?,'APPROVED',NULL)",
            (auth_id, receipt.task_id, encoded, digest(encoded)),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Technical pilot authorization already exists") from exc
    _event(conn, receipt, auth_id, None, "APPROVED", "Interactive local approval")
    return auth_id


def transition(conn, auth_id, state, reason, *, attempt_id=None):
    old, receipt = authorization(conn, auth_id)
    attempt_id = attempt_id or old["attempt_id"]
    conn.execute(
        "UPDATE pilot_authorizations SET state=?,attempt_id=? WHERE authorization_id=?",
        (state, attempt_id, auth_id),
    )
    _event(conn, receipt, auth_id, old["state"], state, reason, attempt_id)
