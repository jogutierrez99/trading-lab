"""Explicit one-shot GitHub intake and separately reviewed Codex preparation."""

import argparse
import json
import os
import sqlite3
from pathlib import Path
from uuid import uuid4

from trading_lab_orchestration.contracts import _unique
from trading_lab_orchestration.github_intake import (
    GitHubUnavailable,
    consume,
    diagnose,
    fetch_issue,
    fetch_issues,
    prepare,
    read_token,
)
from trading_lab_orchestration.implementation import load_plan
from trading_lab_orchestration.readonly import ReadOnlyStore
from trading_lab_orchestration.store import utc_now
from trading_lab_orchestration.workspaces import write_json

REPO = Path(__file__).resolve().parents[1]


def _fixture(path):
    with path.open("rb") as stream:
        raw = stream.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("Issue fixture exceeds limit")
    issues = json.loads(raw, object_pairs_hook=_unique)
    if not isinstance(issues, list) or len(issues) > 150:
        raise ValueError("Expected up to 150 mock issues")
    return issues


def run(args):
    if args.command == "doctor":
        return diagnose(read_token(args.env_file))
    if args.command == "scan":
        token = read_token(args.env_file)
        issues = fetch_issues(token) if args.issue is None else fetch_issue(token, args.issue)
        return {
            "status": "CHECKED" if issues else "NO_PROPOSALS",
            "issues": [{"issue_number": issue["number"]} for issue in issues],
        }
    if args.db is None:
        raise ValueError("--db is required for this command")
    database = args.db.resolve()
    ledger = os.environ.get("TRADING_LAB_GLOBAL_API_DB")
    if database.is_relative_to(REPO) or (ledger and database == Path(ledger).resolve()):
        raise ValueError(
            "Select a local queue outside the checkout, separate from the global ledger"
        )
    if args.command == "poll":
        if args.fixture:
            if args.issue is not None:
                raise ValueError("The Issue selector requires --live-read")
            return consume(
                database, set(args.author_id), lambda: _fixture(args.fixture), source_mode="FIXTURE"
            )
        token = read_token(args.env_file)

        def read_issues():
            if args.issue is not None:
                return fetch_issue(token, args.issue)
            return fetch_issues(token)

        return consume(database, set(args.author_id), read_issues, source_mode="GITHUB")
    if args.command == "list":
        if not database.exists():
            return {"status": "NO_CHECKPOINTS", "issues": []}
        with ReadOnlyStore(database).connection() as conn:
            if (
                conn.execute("SELECT 1 FROM sqlite_master WHERE name='github_intake'").fetchone()
                is None
            ):
                return {"status": "NO_CHECKPOINTS", "issues": []}
            rows = conn.execute(
                """SELECT issue_number, status, reason, task_id, proposal_sha256
                FROM github_intake ORDER BY issue_number DESC LIMIT ?""",
                (args.limit,),
            ).fetchall()
        return {"status": "CHECKED", "issues": list(map(dict, rows))}
    if args.command == "show":
        with ReadOnlyStore(database).connection() as conn:
            row = conn.execute(
                "SELECT * FROM github_intake WHERE issue_number=?", (args.issue,)
            ).fetchone()
        if row is None:
            raise ValueError("Issue checkpoint not found")
        result = dict(row)
        encoded = result.pop("proposal_json")
        return result | {"proposal": json.loads(encoded) if encoded else None}
    if not ledger:
        raise ValueError("TRADING_LAB_GLOBAL_API_DB must identify the existing canonical ledger")
    return prepare(
        database,
        Path(ledger),
        args.issue,
        args.reviewed_sha256,
        REPO,
        args.artifacts,
        load_plan(args.plan),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--env-file", type=Path, help="Read only the GitHub token assignment")
    parser.add_argument("--log-dir", type=Path, help="Write one JSON receipt per poll")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    commands.add_parser("scan").add_argument("--issue", type=int)
    listing = commands.add_parser("list")
    listing.add_argument("--limit", type=int, choices=range(1, 501), default=50, metavar="1..500")
    poll = commands.add_parser("poll")
    poll.add_argument("--author-id", type=int, action="append", required=True)
    poll.add_argument("--issue", type=int, help="With --live-read, fetch only this Issue number")
    mode = poll.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fixture", type=Path)
    mode.add_argument("--live-read", action="store_true")
    show = commands.add_parser("show")
    show.add_argument("--issue", type=int, required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--issue", type=int, required=True)
    prep.add_argument("--reviewed-sha256", required=True)
    prep.add_argument("--plan", type=Path, required=True)
    prep.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    if args.log_dir is not None and args.command != "poll":
        parser.error("--log-dir is supported only for poll")
    log_dir = None
    result = {"status": "BLOCKED", "reason": "Poll interrupted"}
    try:
        if args.log_dir is not None:
            path = args.log_dir.resolve()
            if path.is_relative_to(REPO):
                raise ValueError("Use a log directory outside the checkout")
            path.mkdir(parents=True, exist_ok=True)
            log_dir = path
        result = run(args)
    except GitHubUnavailable as exc:
        result = {"status": "WAITING_GITHUB", "reason": str(exc), "retry_at_epoch": exc.retry_at}
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, sqlite3.Error, RecursionError) as exc:
        status = "WAITING_LOCK" if "owns the OS lock" in str(exc) else "BLOCKED"
        result = {"status": status, "reason": str(exc)}
    if log_dir is not None:
        now = utc_now()
        log_name = now.replace(":", "") + "-" + uuid4().hex + ".json"
        try:
            write_json(log_dir / log_name, {"utc": now, "command": "poll", **result})
        except OSError:
            result = {"status": "BLOCKED", "reason": "Unable to write poll log", "poll": result}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return (
        2
        if result.get("status") in {"BLOCKED", "WAITING_LOCK", "WAITING_BUDGET", "WAITING_GITHUB"}
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
