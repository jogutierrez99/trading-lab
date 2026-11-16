"""Interactive PREPARE_ONLY approval, inspection and one-shot preparation."""

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from trading_lab_orchestration.github_intake import REPO, GitHubUnavailable
from trading_lab_orchestration.implementation import Coordinator, load_plan
from trading_lab_orchestration.pilot_authorization import (
    PilotPreparation,
    PreparationAuthorization,
    approve_authorization,
    authorization,
    current_operator,
)
from trading_lab_orchestration.readonly import ReadOnlyStore
from trading_lab_orchestration.store import Store
from trading_lab_orchestration.workspaces import git


def _run(args):
    reader = ReadOnlyStore(args.db)
    if args.command == "show":
        with reader.connection() as conn:
            row, receipt = authorization(conn, args.authorization_id)
            return {
                "authorization_id": row["authorization_id"],
                "state": row["state"],
                "attempt_id": row["attempt_id"],
                "receipt_sha256": row["receipt_sha256"],
                "receipt": receipt.model_dump(mode="json"),
                "reconciliation_required_if_interrupted": row["state"] in {"RESERVED", "UNKNOWN"},
            }
    if args.command == "close":
        return Coordinator(Store(args.db)).close_pilot_preparation(
            args.authorization_id, args.reason, confirm_stopped=args.confirm_stopped
        )
    plan = load_plan(args.plan)
    repo = Path(git(args.repo, "rev-parse", "--show-toplevel"))
    if args.command == "prepare":
        with reader.connection() as conn:
            _, receipt = authorization(conn, args.authorization_id)
        return Coordinator(Store(args.db)).prepare(
            receipt.task_id,
            repo,
            args.artifacts,
            plan,
            pilot=PilotPreparation(args.authorization_id, args.env_file),
        )
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError("Approval requires an interactive Windows terminal")
    ledger = ReadOnlyStore(args.ledger).path
    if reader.path == ledger:
        raise ValueError("Queue and canonical ledger must be separate")
    account, sid = current_operator()
    receipt = PreparationAuthorization(
        schema_version="1.0",
        repository=REPO,
        issue_number=args.issue,
        issue_id=args.issue_id,
        task_id=args.task_id,
        proposal_sha256=args.proposal_sha256,
        plan_sha256=args.plan_sha256,
        permission="PREPARE_ONLY",
        operation="NEW_STRATEGY",
        approved_by=account,
        approved_at_utc=datetime.now(UTC),
        base_commit=args.base_commit,
        body_sha256=args.body_sha256,
        operator_sid=sid,
        ledger_path=str(ledger),
        max_wall_seconds=plan.max_wall_seconds,
        check_timeout_seconds=plan.check_timeout_seconds,
    )
    auth_id = approve_authorization(
        reader.path,
        receipt,
        plan,
        repo,
        ledger,
        args.env_file,
    )
    return {"authorization_id": auth_id, "state": "APPROVED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    approve = commands.add_parser("approve")
    prepare = commands.add_parser("prepare")
    for sub in (approve, prepare):
        sub.add_argument("--repo", required=True, type=Path)
        sub.add_argument("--plan", required=True, type=Path)
        sub.add_argument("--env-file", type=Path, help="Read only the GitHub intake token")
    approve.add_argument("--issue", required=True, type=int)
    approve.add_argument("--ledger", required=True, type=Path)
    approve.add_argument("--issue-id", required=True, type=int)
    for name in ("task-id", "proposal-sha256", "body-sha256", "plan-sha256", "base-commit"):
        approve.add_argument("--" + name, required=True)
    prepare.add_argument("--authorization-id", required=True)
    prepare.add_argument("--artifacts", required=True, type=Path)
    commands.add_parser("show").add_argument("--authorization-id", required=True)
    close = commands.add_parser("close")
    close.add_argument("--authorization-id", required=True)
    close.add_argument("--reason", required=True)
    close.add_argument("--confirm-stopped", action="store_true")
    try:
        result = _run(parser.parse_args())
    except (OSError, ValueError, sqlite3.Error, GitHubUnavailable, EOFError) as exc:
        result = {"status": "BLOCKED", "reason": str(exc)}
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 2 if result.get("status") in {"BLOCKED", "UNKNOWN"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
