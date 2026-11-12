"""Manually start one bounded sequential Flow 1 acceptance or resume its billing."""

import argparse
import contextlib
import io
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from trading_lab_orchestration.billing import _get, admin_evidence
from trading_lab_orchestration.cli import main as coordinator
from trading_lab_orchestration.workspaces import write_json

REPO = Path(__file__).resolve().parents[1]
RESEARCH_MAX = 4
AUDIT_MAX = 1808
RETRYABLE_BILLING = {"BILLING_TIMEOUT", "COST_NOT_AVAILABLE", "USAGE_INCOMPLETE_OR_DIFFERENT_SCOPE"}


class Stopped(ValueError):
    def __init__(self, stage, result):
        super().__init__(stage)
        self.result = {"stage": stage, **result}


def read(path):
    return json.loads(path.read_bytes())


def check_quote(result, model, input_limit, maximum):
    quote = result["pricing"]
    if (
        result["status"] != "READY"
        or quote["model"] != model
        or quote["input_token_ceiling"] != input_limit
        or quote["output_token_limit"] != 1200
        or quote["maximum_cents"] != maximum
        or result["available_cents"] < maximum
    ):
        raise Stopped("paid-preflight", result)


def wait_billing(poll, call_id, interval, max_wait, *, clock=time.monotonic, sleep=time.sleep):
    start = clock()
    while True:
        state = poll(call_id)
        elapsed = clock() - start
        if state["status"] != "WAITING_BILLING":
            return state | {"poll_seconds": round(elapsed, 2)}
        remaining = max_wait - elapsed
        if state["billing"]["reason_code"] not in RETRYABLE_BILLING or remaining <= 0:
            raise Stopped("billing", state | {"poll_seconds": round(elapsed, 2)})
        sleep(min(interval, remaining))


def finish(poll, diagnose, dispatch, read_review, verify, research_id, interval, max_wait):
    research = wait_billing(poll, research_id, interval, max_wait)
    if research["status"] == "READY_FOR_AUDITOR_PREFLIGHT":
        preflight = diagnose(research["audit_id"])
        check_quote(preflight, "gpt-6.1-sol", 1050000, AUDIT_MAX)
        review = dispatch(research["audit_id"])
    elif research["status"] in {"AUDITOR_ALREADY_RESERVED", "NOTICE_PREPARED"}:
        review = read_review()
    else:
        raise Stopped("research-billing", research)
    audit = wait_billing(poll, review["call_id"], interval, max_wait)
    if audit["status"] != "NOTICE_PREPARED" or audit["billing"]["ledger_status"] != "SETTLED":
        raise Stopped("auditor-billing", audit)
    replay = poll(review["call_id"])
    if (
        replay["status"] != "NOTICE_PREPARED"
        or replay["notification_id"] != audit["notification_id"]
        or replay["billing"]["status"] != "ALREADY_SETTLED"
        or replay["billing"]["released_now_cents"] != 0
    ):
        raise Stopped("replay", replay)
    return {
        "status": "NOTICE_PREPARED",
        "research": research,
        "audit": audit,
        "replay": replay,
        "verification": verify(audit),
    }


def run(args):
    from trading_lab_orchestration.audit_model import Budget, ExistingBudgetStore
    from trading_lab_orchestration.readonly import ReadOnlyStore

    root, ledger = args.root.resolve(), args.ledger.resolve()
    env_ledger = os.environ.get("TRADING_LAB_GLOBAL_API_DB")
    if not env_ledger or Path(env_ledger).resolve() != ledger:
        raise ValueError("Explicit ledger must match TRADING_LAB_GLOBAL_API_DB")
    if (
        root.is_relative_to(REPO)
        or root.is_relative_to(ledger.parent)
        or ledger.is_relative_to(root)
    ):
        raise ValueError("Use a separate local acceptance directory")
    db = root / "state" / "trial.sqlite3"
    research = root / "research"
    audit = root / "model-audit"
    request = root / "circuit-request.json"
    artifacts = root / "circuit"
    journal = root / "acceptance.jsonl"
    intake_path = root / "intake.json"
    config_path = root / "acceptance.json"
    scope = [args.organization, args.project]
    if not re.fullmatch(r"org-[a-zA-Z0-9_-]+", args.organization) or not re.fullmatch(
        r"proj_[a-zA-Z0-9_-]+", args.project
    ):
        raise ValueError("Expected explicit organization and project IDs")
    config = {
        "ledger": str(ledger),
        "scope": scope,
        "interval_seconds": args.interval_seconds,
        "max_wait_seconds": args.max_wait_seconds,
        "acceptance_id": args.acceptance_id,
    }

    def invoke(database, command, *options):
        argv = ["--db", str(database), command, *map(str, options)]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = coordinator(argv)
        result = json.loads(output.getvalue())
        event = {"utc": datetime.now(UTC).isoformat(), "command": command, "result": result}
        if root.is_dir():
            with journal.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=True) + "\n")
        print(
            json.dumps(
                {
                    "command": command,
                    "status": result.get("status"),
                    "reason": (result.get("billing") or {}).get("reason_code"),
                }
            ),
            flush=True,
            file=sys.stderr,
        )
        if code:
            raise Stopped(command, result)
        return result

    if args.resume:
        if read(config_path) != config:
            raise ValueError("Resume requires the original acceptance configuration")
        intake = read(intake_path)
    else:
        if root.exists():
            raise ValueError("Acceptance directory exists; inspect it or use --resume")
        preflight = invoke(
            db,
            "circuit-doctor",
            REPO / "examples/orchestration/circuit46.json",
            "--repo",
            REPO,
            "--artifacts",
            artifacts,
        )
        if preflight["status"] != "LOCAL_PREFLIGHT_OK":
            raise Stopped("local-preflight", preflight)
        available = Budget(ExistingBudgetStore(ledger)).available()
        if available < RESEARCH_MAX + AUDIT_MAX:
            raise ValueError("Insufficient global balance for the two reviewed maxima")
        day = int(datetime.now(UTC).timestamp()) // 86400 * 86400
        key = os.environ.get("OPENAI_ADMIN_KEY", "").strip()
        if not key:
            raise ValueError("OPENAI_ADMIN_KEY missing")
        project = json.loads(_get("projects/" + args.project, {}, key, args.organization))
        if project["id"] != args.project or project["status"] != "active":
            raise ValueError("Billing project is not active or does not match the requested scope")
        admin_evidence(day, args.project, organization=args.organization)
        root.mkdir(parents=True, exist_ok=False)
        write_json(config_path, config)
        batch = read(REPO / "examples/orchestration/research_batch_flow1_sequential.json")
        batch["source_reference"] = "local:flow1-unattended:" + args.acceptance_id
        batch_path = root / "batch.json"
        write_json(batch_path, batch)
        quote = invoke(
            ledger, "research-doctor", batch_path, "--budget-db", ledger, "--profile", "reduced"
        )
        check_quote(quote, "gpt-4o-mini-2024-07-18", 128000, RESEARCH_MAX)
        intake = invoke(
            db,
            "research-intake",
            batch_path,
            "--budget-db",
            ledger,
            "--profile",
            "reduced",
            "--artifacts",
            research,
            "--confirm-maximum-cents",
            RESEARCH_MAX,
            "--billing-scope",
            *scope,
        )
        write_json(intake_path, intake)
        if intake["status"] != "REGISTERED" or intake["queue_status"] != "QUEUED":
            raise Stopped("research-intake", intake)
        binding = invoke(
            db, "flow1-bind", "--budget-db", ledger, "--research-dossier", intake["dossier"]
        )
        write_json(request, binding)
        invoke(db, "circuit-doctor", request, "--repo", REPO, "--artifacts", artifacts)
        circuit = invoke(db, "circuit-run", request, "--repo", REPO, "--artifacts", artifacts)
        if circuit["status"] != "AWAITING_MODEL_AUDIT" or circuit["task_id"] != intake["task_id"]:
            raise Stopped("circuit-run", circuit)

    def poll(call):
        return invoke(
            db,
            "flow1-billing-cycle",
            call,
            "--budget-db",
            ledger,
            "--project-id",
            args.project,
            "--research-dossier",
            intake["dossier"],
            "--model-dossier",
            audit,
        )

    def diagnose(audit_id):
        return invoke(ledger, "audit-openai-doctor", audit_id, "--source-db", db)

    def dispatch(audit_id):
        return invoke(
            ledger,
            "audit-openai",
            audit_id,
            "--source-db",
            db,
            "--artifacts",
            audit,
            "--confirm-maximum-cents",
            AUDIT_MAX,
            "--billing-scope",
            *scope,
        )

    def verify(state):
        trial = ReadOnlyStore(db)
        with trial.connection() as conn:
            counts = {
                table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ("tasks", "executions", "audits", "audit_outbox")
            }
        notice = invoke(db, "notify-show", state["notification_id"])
        if set(counts.values()) != {1} or notice["status"] != "DRAFT" or notice["attempts"] != 0:
            raise Stopped("verify", {"counts": counts, "notice": notice})
        return {"counts": counts, "notice": notice}

    return finish(
        poll,
        diagnose,
        dispatch,
        lambda: read(audit / "review_receipt.json"),
        verify,
        intake["call_id"],
        args.interval_seconds,
        args.max_wait_seconds,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "ledger"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("organization", "project", "acceptance-id"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument(
        "--interval-seconds", type=int, default=30, choices=range(5, 121), metavar="5..120"
    )
    parser.add_argument(
        "--max-wait-seconds", type=int, default=300, choices=range(5, 1801), metavar="5..1800"
    )
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        result = run(args)
    except Stopped as exc:
        print(json.dumps(exc.result, indent=2))
        return 2
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, indent=2))
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
