"""Operator entry point for the frozen Issue #3 historical pilot."""

import argparse
import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path

from trading_lab_orchestration import historical_pilot as pilot
from trading_lab_orchestration import historical_pilot_store as store
from trading_lab_orchestration import study_storage_windows as ntfs
from trading_lab_orchestration.verification_container import ENDPOINT

BASE_COMMIT = "b726ecf174bf3a87e0d550510cbd6c947e3c7826"
JOB_SHA256 = "c8fefa01f00bfae7c303115c19b305ccbad76b19321f1e1a5e923627e28c1b42"
RECEIPT_SHA256 = "7d5b48c8d07d0b4ee7a1b2262591161b0e58ee6c046dc6ece98ed11fc5309a40"
RELEASE_PATHS = {
    "scripts/operate_historical_pilot.py",
    "tests/unit/test_operate_historical_pilot.py",
    "docs/orchestration-phase-5-5b.md",
    "docs/PROJECT_STATE.md",
    "src/trading_lab_orchestration/historical_pilot.py",
    "src/trading_lab_orchestration/historical_pilot_store.py",
    "src/trading_lab_orchestration/readonly.py",
    "tests/unit/test_historical_pilot.py",
}


class Blocked(ValueError):
    """An operator-facing reason containing no private paths or identities."""


def _checkout(expected):
    if Path(__file__).resolve().parents[1] != pilot.ROOT.resolve():
        raise Blocked("Historical supervisor was imported from another checkout")

    def git(*args):
        return subprocess.run(
            ["git", "--no-optional-locks", "-C", str(pilot.ROOT), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout.strip()

    if (
        git("symbolic-ref", "--quiet", "HEAD") != "refs/heads/main"
        or git("rev-parse", "HEAD") != expected
        or git("status", "--porcelain", "--untracked-files=all")
    ):
        raise Blocked("Expected a clean main checkout at the reviewed release commit")
    git("merge-base", "--is-ancestor", BASE_COMMIT, expected)
    git("ls-files", "--error-unmatch", "scripts/operate_historical_pilot.py")
    if set(git("diff", "--name-only", "--no-renames", BASE_COMMIT, expected).splitlines()) - (
        RELEASE_PATHS
    ):
        raise Blocked("Release changes files outside the historical CLI review scope")


def _inspect_image(verifier, scratch):
    config = scratch / ".historical-inspect-config"
    # Only inspect against the local Linux endpoint. Do not use ambient Docker
    # context, credentials or config. Inspect creates no logs or containers.
    if os.path.lexists(config):
        raise Blocked("Reserved Docker inspection config path must be absent")
    command = [
        str(verifier.docker),
        "--config",
        str(config),
        "--host",
        ENDPOINT,
        "image",
        "inspect",
        verifier.image,
    ]
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("DOCKER_")}
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
    if result.returncode or len(result.stdout) > pilot.LOG_LIMIT:
        raise Blocked("Approved local Linux image could not be inspected")
    metadata = json.loads(result.stdout)
    if (
        not isinstance(metadata, list)
        or len(metadata) != 1
        or metadata[0]["Id"] != verifier.image
        or metadata[0]["Os"] != "linux"
        or metadata[0]["Config"].get("Volumes")
    ):
        raise Blocked("Approved local Linux image is unavailable or declares volumes")


def _operation(args, registry, scratch):
    verifier = pilot.HistoricalVerifier()
    job, _, evidence = pilot.prepare(verifier, data_repo=args.data_repo)
    if pilot.plan_sha(job) != JOB_SHA256:
        raise Blocked("Historical job SHA-256 does not match the frozen proposal")
    attempt, receipt_sha, operator, sid = pilot._verified_binding(args.coordinator_db)
    if receipt_sha != RECEIPT_SHA256:
        raise Blocked("Original implementation receipt does not match the frozen receipt")
    store.check_acl(registry, sid, private=True)
    store.check_acl(scratch, sid, private=True)
    _inspect_image(verifier, scratch)
    record, state = store.historical_status(registry / pilot.DB, store.ISSUE_SCOPE, (operator, sid))
    if record:
        key, permit = record
        binding = (
            permit.attempt_id,
            permit.implementation_receipt_sha256,
            permit.operator,
            permit.operator_sid,
        )
        if (
            permit.purpose != "HISTORICAL_BACKTEST_ONCE"
            or permit.job_sha256 != JOB_SHA256
            or binding != (attempt, receipt_sha, operator, sid)
        ):
            raise Blocked("Historical permit does not match the frozen work and operator")

    if args.command != "run" and state is not None:
        if state in {"RESERVED", "UNKNOWN"}:
            raise pilot.IsolationUncertain(
                "Historical reservation requires operator reconciliation"
            )
        raise Blocked("The historical authorization has already been consumed")
    if args.command == "preflight":
        return {
            "status": "HISTORICAL_PREFLIGHT_PASSED",
            "job_sha256": JOB_SHA256,
            "image": verifier.image,
            "dataset_sha256": evidence["parquet_sha256"],
            "manifest_sha256": evidence["manifest_sha256"],
            "cases": [case.id for case in job.plan.cases],
            "limits": job.plan.limits.model_dump(mode="json"),
            "transport_limit_exclusive_bytes": pilot.WIRE_LIMIT,
            "evidence_limit_exclusive_bytes": pilot.BUNDLE_LIMIT,
            "registry": "APPROVED" if record else "NO_PERMIT",
        }
    if args.command == "approve":
        if record:
            raise Blocked("A historical permit already exists")
        print("Review BTCUSDT spot 1h, SMA50/SMA200, BASE and ADVERSE, and the six dates below.")
        print("TEST is retrospective. Approval grants one lot; the run consumes it before Docker.")
        print("A timeout or uncertain result requires manual reconciliation and cannot be retried.")
        permit_id = pilot.approve_historical(
            args.data_repo, args.coordinator_db, registry, expected_job_sha256=JOB_SHA256
        )
        return {"status": "APPROVED", "permit_id": permit_id}

    if not record or key != args.permit_id:
        raise Blocked("The exact persisted historical permit ID is required")
    if state in {"RESERVED", "UNKNOWN"}:
        raise pilot.IsolationUncertain("Historical reservation requires operator reconciliation")
    try:
        result = pilot.run_historical(args.data_repo, args.coordinator_db, registry, scratch, key)
    except (ValueError, OSError, sqlite3.Error) as exc:
        raise pilot.IsolationUncertain(
            "Historical execution or its sealed evidence requires operator reconciliation"
        ) from exc
    return {
        "status": result["status"],
        "job_sha256": result["job_sha256"],
        "stdout_sha256": result["stdout_sha256"],
        "previously_sealed": state == "SEALED",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("preflight", "approve", "run"):
        sub = commands.add_parser(command)
        sub.add_argument("--checkout-commit", required=True, metavar="SHA")
        for flag in ("data-repo", "coordinator-db", "registry", "scratch"):
            sub.add_argument("--" + flag, type=Path, required=True)
        if command == "run":
            sub.add_argument("--permit-id", required=True)
    args = parser.parse_args(argv)

    try:
        if not re.fullmatch("[a-f0-9]{40}", args.checkout_commit):
            raise Blocked("Pass the exact reviewed CLI release commit")
        _checkout(args.checkout_commit)
        with (
            ntfs.pinned_root(args.registry, existing=True) as registry,
            ntfs.pinned_root(args.scratch, existing=True) as scratch,
        ):
            pilot._paths(registry, scratch)
            for storage in (registry, scratch):
                for protected in (pilot.ROOT, args.data_repo, args.coordinator_db.parent):
                    if storage.is_relative_to(
                        protected.resolve()
                    ) or protected.resolve().is_relative_to(storage):
                        raise Blocked(
                            "Historical storage must be outside code, data and coordinator roots"
                        )
            args.registry = registry
            result = _operation(args, registry, scratch)
    except pilot.IsolationUncertain:
        result = {
            "status": "BLOCKED",
            "reason": "Historical reservation requires operator reconciliation",
        }
    except (EOFError, KeyboardInterrupt):
        result = {
            "status": "BLOCKED",
            "reason": "Interrupted; inspect the registry before any further action",
        }
    except (subprocess.SubprocessError, OSError, sqlite3.Error):
        result = {
            "status": "BLOCKED",
            "reason": "Local Git, Windows, storage or Docker check failed",
        }
    except Blocked as exc:
        result = {"status": "BLOCKED", "reason": str(exc).splitlines()[0]}
    except (ValueError, KeyError):
        result = {"status": "BLOCKED", "reason": "Historical verification or confirmation failed"}
    print(json.dumps(result, allow_nan=False))
    return 2 if result["status"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
