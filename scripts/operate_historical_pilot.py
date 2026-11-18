"""Operator entry point for the frozen Issue #3 historical pilot."""

import argparse
import ctypes
import json
import os
import re
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from trading_lab_orchestration import historical_pilot as pilot
from trading_lab_orchestration import historical_pilot_store as store
from trading_lab_orchestration import study_storage_windows as ntfs
from trading_lab_orchestration.verification_container import ENDPOINT

BASE_COMMIT = "b726ecf174bf3a87e0d550510cbd6c947e3c7826"
JOB_SHA256 = "bed1315307979dba449b3137e84b65ae11f09d63a8ffeb7d6e8dbaf03a448670"
RECEIPT_SHA256 = "7d5b48c8d07d0b4ee7a1b2262591161b0e58ee6c046dc6ece98ed11fc5309a40"
RELEASE_PATHS = {
    "scripts/operate_historical_pilot.py",
    "tests/unit/test_operate_historical_pilot.py",
    "docs/orchestration-phase-5-5b.md",
    "docs/PROJECT_STATE.md",
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


def _require_designated_registry(registry):
    # Use the Windows profile API instead of accepting a caller-provided LocalAppData.
    local = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x001C, None, 0, local) or not local.value:
        raise Blocked("Windows LocalAppData folder is unavailable")
    if registry != Path(local.value) / "TradingLab/HistoricalPilot55B":
        raise Blocked("Use the designated HistoricalPilot55B registry")


def _windows_acl(registry, scratch, sid):
    # Read ACLs with the existing token. Reject grants to other principals,
    # including groups, rather than guessing their membership or resolving localized names.
    script = r"""
    $ErrorActionPreference = 'Stop'
    $trusted = @($env:TL55B_OPERATOR_SID, 'S-1-5-18', 'S-1-5-32-544', 'S-1-3-4')
    $paths = @($env:TL55B_REGISTRY, $env:TL55B_SCRATCH)
    $db = Join-Path $env:TL55B_REGISTRY 'historical-pilot.sqlite3'
    if ([IO.File]::Exists($db)) { $paths += $db }
    $sidType = [Security.Principal.SecurityIdentifier]
    foreach ($path in $paths) {
        if ($path -eq $db) { $acl = [IO.File]::GetAccessControl($path) }
        else { $acl = [IO.Directory]::GetAccessControl($path) }
        if ($acl.GetOwner($sidType).Value -ne $env:TL55B_OPERATOR_SID) {
            throw 'Historical storage must be owned by the Windows operator'
        }
        foreach ($rule in $acl.GetAccessRules($true, $true, $sidType)) {
            if ($rule.AccessControlType -eq 'Allow' `
                -and $rule.IdentityReference.Value -notin $trusted) {
                throw 'Historical storage ACL permits another principal'
            }
        }
    }
    """
    env = dict(
        os.environ,
        TL55B_REGISTRY=str(registry),
        TL55B_SCRATCH=str(scratch),
        TL55B_OPERATOR_SID=sid,
    )
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
        env=env,
        capture_output=True,
        timeout=15,
    )
    if result.returncode:
        raise Blocked("Designated registry or scratch owner/ACL verification failed")
    for root in (registry, scratch):
        # READ_CONTROL | FILE_READ_ATTRIBUTES | FILE_ADD_FILE | FILE_ADD_SUBDIRECTORY.
        # Windows checks the process token on the directory without creating a canary.
        handle = ntfs._open_no_reparse(
            root, 0x20086, ntfs.SHARE_READ | ntfs.SHARE_WRITE, 1, is_directory=True
        )
        try:
            ntfs._info(handle, directory=True)
        finally:
            ntfs.close_handle(handle)


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


def _registry(database, scope):
    if not os.path.lexists(database):
        return None, None
    handle = ntfs._open_no_reparse(database, ntfs.READ, ntfs.SHARE_READ | ntfs.SHARE_WRITE, 1)
    try:
        ntfs._info(handle)
        # The dedicated store uses rollback journals. Do not open a WAL database
        # from this read-only command, since opening WAL can create a sidecar.
        if any(
            os.path.lexists(database.with_name(database.name + suffix))
            for suffix in ("-wal", "-shm")
        ):
            raise Blocked("Unexpected historical registry sidecar")
        with database.open("rb") as raw:
            header = raw.read(100)
        if header[18:20] != b"\x01\x01":
            raise Blocked("Expected a rollback-journal historical registry")
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=5)) as conn:
            conn.execute("PRAGMA query_only=ON")
            if (
                conn.execute("PRAGMA application_id").fetchone()[0] != store.APP_ID
                or conn.execute("PRAGMA user_version").fetchone()[0] != 1
            ):
                raise Blocked("Unrecognized historical authorization database")
            row = conn.execute(
                """SELECT p.id, p.receipt, p.confirmation, r.state
                   FROM permits p LEFT JOIN runs r ON r.permit=p.id WHERE p.scope=?""",
                (scope,),
            ).fetchone()
    finally:
        ntfs.close_handle(handle)
    if row is None:
        return None, None
    key, raw, confirmation, state = row
    permit = store.Permit.model_validate_json(raw)
    if (
        permit.scope != scope
        or key != store.receipt_id(permit)
        or confirmation != store.phrase(permit)
    ):
        raise Blocked("Stored historical permit receipt or confirmation was altered")
    return (key, permit), state


def _interactive():
    if os.name != "nt" or not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise Blocked("A personal confirmation in an interactive Windows terminal is required")


def _approve(args, permit):
    _interactive()
    expected = f"Type {store.phrase(permit)} to authorize these six cases: "
    binding = (
        permit.attempt_id,
        permit.implementation_receipt_sha256,
        permit.operator,
        permit.operator_sid,
    )
    # The frozen supervisor rebuilds its proposal immediately before input().
    # Bind the actual interactive prompt to the reviewed proposal as well.
    active = True
    installed = False

    def audit(event, values):
        nonlocal installed
        if event == "trading_lab.historical_approval_guard" and values == (audit,):
            installed = True
        if active and event == "builtins.input":
            if values != (expected,) or pilot._verified_binding(args.coordinator_db) != binding:
                raise Blocked("The interactive proposal no longer matches the reviewed work")

    sys.addaudithook(audit)
    sys.audit("trading_lab.historical_approval_guard", audit)
    try:
        if not installed:
            raise Blocked("Cannot bind the interactive approval to the reviewed work")
        return pilot.approve_historical(args.data_repo, args.coordinator_db, args.registry)
    finally:
        active = False


def _operation(args, registry, scratch):
    verifier = pilot.HistoricalVerifier()
    job, _, evidence = pilot.prepare(verifier, data_repo=args.data_repo)
    if pilot.plan_sha(job) != JOB_SHA256:
        raise Blocked("Historical job SHA-256 does not match the frozen proposal")
    attempt, receipt_sha, operator, sid = pilot._verified_binding(args.coordinator_db)
    if receipt_sha != RECEIPT_SHA256:
        raise Blocked("Original implementation receipt does not match the frozen receipt")
    _windows_acl(registry, scratch, sid)
    _inspect_image(verifier, scratch)
    record, state = _registry(registry / pilot.DB, f"issue-3:{attempt}")
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
        permit = store.Permit(
            purpose="HISTORICAL_BACKTEST_ONCE",
            attempt_id=attempt,
            implementation_receipt_sha256=receipt_sha,
            job_sha256=JOB_SHA256,
            operator=operator,
            operator_sid=sid,
            approved_at=datetime.now(UTC),
        )
        print("Review BTCUSDT spot 1h, SMA50/SMA200, BASE and ADVERSE, and the six dates below.")
        print("TEST is retrospective. Approval grants one lot; the run consumes it before Docker.")
        print("A timeout or uncertain result requires manual reconciliation and cannot be retried.")
        return {"status": "APPROVED", "permit_id": _approve(args, permit)}

    if not record or key != args.permit_id:
        raise Blocked("The exact persisted historical permit ID is required")
    if state in {"RESERVED", "UNKNOWN"}:
        raise pilot.IsolationUncertain("Historical reservation requires operator reconciliation")
    if state is None:
        _interactive()
        phrase = f"RUN HISTORICAL_BACKTEST_ONCE {key}"
        if input(f"Type {phrase} to consume the permit and start the historical lot: ") != phrase:
            raise Blocked("Explicit historical execution confirmation did not match")
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
        if args.command == "approve":
            _interactive()
        _checkout(args.checkout_commit)
        with (
            ntfs.pinned_root(args.registry, existing=True) as registry,
            ntfs.pinned_root(args.scratch, existing=True) as scratch,
        ):
            pilot._paths(registry, scratch)
            _require_designated_registry(registry)
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
