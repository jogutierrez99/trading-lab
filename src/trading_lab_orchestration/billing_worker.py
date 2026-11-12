"""One bounded billing pass over an explicit allowlist of Flow 1 dossiers."""

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from .contracts import digest
from .processes import WindowsJob, coordinator_lock
from .readonly import ReadOnlyStore

REPO = Path(__file__).resolve().parents[2]
WAIT_CODES = {
    "BILLING_TIMEOUT",
    "BILLING_UNAVAILABLE",
    "COST_NOT_AVAILABLE",
    "USAGE_INCOMPLETE_OR_DIFFERENT_SCOPE",
}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _save(path, value):
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def invoke(database, command, *options, timeout):
    argv = [
        sys.executable,
        "-B",
        str(REPO / "scripts/orchestrator.py"),
        "--db",
        str(database),
        command,
        *map(str, options),
    ]
    if os.name == "nt":
        job = WindowsJob()
        try:
            with subprocess.Popen(
                argv,
                cwd=REPO,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=0x00000004 | 0x08000000,  # Suspended, without a console window.
            ) as child:
                try:
                    job.assign(child)
                    job.resume(child)
                    output, _ = child.communicate(timeout=timeout)
                finally:
                    job.close()
                    if child.poll() is None:
                        child.kill()
                code = child.returncode
        finally:
            job.close()
    else:
        result = subprocess.run(argv, cwd=REPO, capture_output=True, timeout=timeout, check=False)
        output, code = result.stdout, result.returncode
    try:
        payload = json.loads(output)
    except ValueError:
        raise ValueError("Coordinator returned no valid structured result") from None
    if code:
        raise ValueError(json.dumps({"command": command, "result": payload}))
    return payload


def load_config(path):
    config = read(path)
    if (
        set(config)
        != {
            "schema_version",
            "ledger",
            "state_directory",
            "dossiers",
            "interval_seconds",
            "max_age_hours",
            "invocation_seconds",
            "allow_model_audit",
            "secrets_env_file",
        }
        or config["schema_version"] != "1.0"
    ):
        raise ValueError("Unsupported billing worker configuration")
    for key, minimum, maximum in (
        ("interval_seconds", 60, 3600),
        ("max_age_hours", 7, 168),
        ("invocation_seconds", 30, 300),
    ):
        if type(config[key]) is not int or not minimum <= config[key] <= maximum:
            raise ValueError("Invalid worker limit: " + key)
    if type(config["allow_model_audit"]) is not bool:
        raise ValueError("allow_model_audit requires an explicit boolean")
    roots = config["dossiers"]
    if not isinstance(roots, list) or not 1 <= len(roots) <= 16:
        raise ValueError("Supply 1 to 16 explicit dossier directories")
    for name in ("ledger", "state_directory", "secrets_env_file"):
        if not Path(config[name]).is_absolute():
            raise ValueError("Worker paths must be absolute")
    resolved = [Path(root).resolve() for root in roots]
    if any(not Path(root).is_absolute() for root in roots) or len(set(resolved)) != len(roots):
        raise ValueError("Dossier paths must be absolute and unique")
    ledger = Path(config["ledger"]).resolve()
    state = Path(config["state_directory"]).resolve()
    if (
        state.is_relative_to(REPO)
        or any(state.is_relative_to(root) or root.is_relative_to(state) for root in resolved)
        or state == ledger.parent
        or ledger.is_relative_to(state)
    ):
        raise ValueError("Worker state must be separate from dossiers, ledger and repository")
    canonical = os.environ.get("TRADING_LAB_GLOBAL_API_DB")
    if canonical and Path(canonical).resolve() != ledger:
        raise ValueError("Worker requires the canonical TRADING_LAB_GLOBAL_API_DB")
    return config


def poll_dossier(root, config, call, now):
    """Inspect the saved reservation before deciding what can safely continue."""
    acceptance = read(root / "acceptance.json")
    intake = read(root / "intake.json")
    ledger = Path(config["ledger"]).resolve()
    if Path(acceptance["ledger"]).resolve() != ledger:
        raise ValueError("Dossier ledger differs from worker configuration")
    database = root / "state/trial.sqlite3"
    circuit = call(database, "circuit-show", "flow1_seq_v1")
    if circuit["task_id"] != intake["task_id"]:
        raise ValueError("Dossier task differs from the saved circuit")
    if circuit["status"] not in {"AWAITING_MODEL_AUDIT", "NOTICE_PREPARED"}:
        return {"status": "REVIEW_REQUIRED", "reason": "Circuit has no saved deterministic audit"}
    purpose = "openai-audit-v1:" + circuit["execution_id"]
    with ReadOnlyStore(ledger).connection() as conn:
        entries = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM api_calls WHERE call_id=? OR purpose=?", (intake["call_id"], purpose)
            )
        ]
    research = next((r for r in entries if r["call_id"] == intake["call_id"]), None)
    if research is None:
        raise ValueError("Research reservation is missing")
    audit = [r for r in entries if r["purpose"] == purpose]
    if len(audit) > 1:
        raise ValueError("More than one auditor reservation")
    closed = circuit["status"] == "NOTICE_PREPARED"
    if closed and (not audit or any(r["status"] != "SETTLED" for r in (research, audit[0]))):
        return {"status": "REVIEW_REQUIRED", "reason": "Closed circuit has unsettled billing"}
    target = research if research["status"] != "SETTLED" or not audit else audit[0]
    age = now - datetime.fromisoformat(target["created_at_utc"])
    if (target["status"] != "SETTLED" or not audit) and (
        age < timedelta(0) or age > timedelta(hours=config["max_age_hours"])
    ):
        return {
            "status": "REVIEW_REQUIRED",
            "reason": "Reservation outside maximum age",
            "call_id": target["call_id"],
        }
    if target["status"] == "RESERVED":
        return {
            "status": "REVIEW_REQUIRED",
            "reason": "Provider outcome requires reconciliation",
            "call_id": target["call_id"],
        }
    options = (
        "--budget-db",
        ledger,
        "--research-dossier",
        intake["dossier"],
        "--model-dossier",
        root / "model-audit",
        "--project-id",
        acceptance["scope"][1],
    )
    result = call(database, "flow1-billing-cycle", target["call_id"], *options)
    if result["status"] == "READY_FOR_AUDITOR_PREFLIGHT":
        diagnostic = call(
            ledger, "audit-openai-doctor", circuit["audit_id"], "--source-db", database
        )
        quote = diagnostic["pricing"]
        if (
            diagnostic["status"] != "READY"
            or diagnostic["available_cents"] < 1808
            or (
                quote["model"],
                quote["input_token_ceiling"],
                quote["output_token_limit"],
                quote["maximum_cents"],
            )
            != ("gpt-6.1-sol", 1050000, 1200, 1808)
        ):
            return {"status": "REVIEW_REQUIRED", "diagnostic": diagnostic}
        if not config["allow_model_audit"]:
            return {"status": "AUDITOR_AUTHORIZATION_REQUIRED", "diagnostic": diagnostic}
        receipt = call(
            ledger,
            "audit-openai",
            circuit["audit_id"],
            "--source-db",
            database,
            "--artifacts",
            root / "model-audit",
            "--confirm-maximum-cents",
            1808,
            "--billing-scope",
            *acceptance["scope"],
        )
        return {
            "status": "WAITING_BILLING",
            "call_id": receipt["call_id"],
            "review_status": receipt["status"],
        }
    if result["status"] == "NOTICE_PREPARED":
        if closed and (
            result["notification_id"] != circuit["notification_id"]
            or result["billing"]["status"] != "ALREADY_SETTLED"
        ):
            raise ValueError("Closed circuit did not return its original settled notice")
        notice = call(database, "notify-show", result["notification_id"])
        if notice["status"] != "DRAFT" or notice["attempts"] or notice["message_id"] is not None:
            raise ValueError("Expected the same unsent DRAFT")
        return {
            "status": "NOTICE_PREPARED",
            "notification_id": notice["notification_id"],
            "billing": result["billing"],
        }
    if result["status"] == "WAITING_GLOBAL_LEDGER":
        return result
    if result["status"] == "WAITING_BILLING":
        if result["billing"]["reason_code"] not in WAIT_CODES:
            return {"status": "REVIEW_REQUIRED", "billing": result["billing"]}
    else:
        return {"status": "REVIEW_REQUIRED", "result": result}
    return result


def tick(config, *, execute=invoke, now=None):
    now = now or datetime.now(UTC)
    started = time.monotonic()
    state_dir = Path(config["state_directory"])
    state_dir.mkdir(parents=True, exist_ok=True)
    results = []

    def call(database, command, *options):
        remaining = config["invocation_seconds"] - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("Invocation deadline reached")
        return execute(database, command, *options, timeout=remaining)

    # One lock per canonical ledger also excludes differently configured workers.
    lock = Path(config["ledger"]).resolve().with_suffix(".flow1-billing-worker.lock")
    try:
        with coordinator_lock(lock):
            for name in config["dossiers"]:
                if time.monotonic() - started >= config["invocation_seconds"]:
                    break
                root = Path(name).resolve()
                state_path = state_dir / (digest(str(root)) + ".json")
                state = read(state_path) if state_path.exists() else {}
                if state.get("status") == "REVIEW_REQUIRED":
                    results.append({"dossier": str(root), **state})
                    continue
                if (
                    state.get("status") != "NOTICE_PREPARED"
                    and state.get("next_poll_utc")
                    and now < datetime.fromisoformat(state["next_poll_utc"])
                ):
                    results.append(
                        {
                            "dossier": str(root),
                            "status": "NOT_DUE",
                            "next_poll_utc": state["next_poll_utc"],
                        }
                    )
                    continue
                next_poll = (now + timedelta(seconds=config["interval_seconds"])).isoformat()
                # Persist before I/O. A killed worker leaves a checkpoint, never a resend intent.
                _save(state_path, {"status": "INSPECT_EXISTING", "next_poll_utc": next_poll})
                try:
                    result = poll_dossier(root, config, call, now)
                except (TimeoutError, subprocess.TimeoutExpired):
                    result = {"status": "WAITING_BILLING", "reason": "Invocation or GET timed out"}
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    result = {"status": "REVIEW_REQUIRED", "reason": str(exc)}
                saved = {"next_poll_utc": next_poll, "checked_at_utc": now.isoformat(), **result}
                _save(state_path, saved)
                results.append({"dossier": str(root), **saved})
    except ValueError as exc:
        if "owns the OS lock" not in str(exc):
            raise
        return {"status": "BUSY", "dossiers": []}
    return {"status": "CHECKED", "dossiers": results}
