import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from trading_lab_orchestration import billing, billing_snapshots
from trading_lab_orchestration.audit_model import Budget
from trading_lab_orchestration.billing_worker import tick
from trading_lab_orchestration.contracts import digest
from trading_lab_orchestration.processes import coordinator_lock
from trading_lab_orchestration.store import Store


@pytest.fixture
def worker(tmp_path, monkeypatch):
    ledger = Budget(Store(tmp_path / "ledger/api.sqlite3"))
    ledger.open_month(0, "Offline billing worker")
    root = tmp_path / "dossier"
    root.mkdir()
    ledger_path = str(ledger.store.path)
    config = {
        "schema_version": "1.0",
        "ledger": ledger_path,
        "state_directory": str(tmp_path / "worker"),
        "dossiers": [str(root)],
        "interval_seconds": 300,
        "max_age_hours": 48,
        "invocation_seconds": 120,
        "allow_model_audit": False,
        "secrets_env_file": str(tmp_path / ".env"),
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("TRADING_LAB_GLOBAL_API_DB", ledger_path)
    monkeypatch.setenv("OPENAI_ADMIN_KEY", "simulated")
    created = datetime.now(UTC)
    start = int(created.timestamp()) // 86400 * 86400
    # Both checkpoints retain this original UTC interval on the following day.
    published = False
    usage = {
        "project_id": "proj_fixture",
        "model": billing.REDUCED,
        "service_tier": "default",
        "num_model_requests": 1,
        "input_tokens": 1000,
        "output_tokens": 100,
        "input_cached_tokens": 0,
    }
    source_reads = []

    def get(endpoint, query, key, org):
        assert org == "org-fixture" and query["start_time"] == start
        source_reads.append(endpoint)
        if endpoint == "usage/completions":
            rows = [usage] if sent else []
        else:
            rows = (
                [
                    {
                        "organization_id": org,
                        "project_id": "proj_fixture",
                        "line_item": f"{billing.REDUCED}, {direction}",
                        "quantity_unit": "tokens",
                        "quantity": quantity,
                        "amount": {"value": value, "currency": "usd"},
                    }
                    for direction, quantity, value in (
                        ("input", 1000, "0.00015"),
                        ("output", 100, "0.00006"),
                    )
                ]
                if published
                else []
            )
        return json.dumps(
            {
                "has_more": False,
                "data": [{"start_time": start, "end_time": start + 86400, "results": rows}],
            }
        ).encode()

    monkeypatch.setattr(billing, "_get", get)
    sent = False
    provider = type("Provider", (), {"billing_scope": ("org-fixture", "proj_fixture")})()
    baseline = billing_snapshots.capture_baseline(ledger, provider, 4)
    call_id = ledger.reserve("openai", "openai-research-v1:fixture", 4, once=True)
    ledger.settle(
        call_id,
        None,
        json.dumps(
            {
                "usage": {"input_tokens": 1000, "output_tokens": 100, "cached_input_tokens": 0},
                "pricing": {"model": billing.REDUCED, "service_tier": "default"},
                **baseline,
            }
        ),
    )
    sent = True
    (root / "acceptance.json").write_text(
        json.dumps({"ledger": ledger_path, "scope": ["org-fixture", "proj_fixture"]}),
        encoding="utf-8",
    )
    (root / "intake.json").write_text(
        json.dumps(
            {"task_id": "task_original", "call_id": call_id, "dossier": str(root / "research")}
        ),
        encoding="utf-8",
    )
    invocations = []

    def execute(database, command, *options, timeout):
        assert 0 < timeout <= 120
        invocations.append(command)
        if command == "circuit-show":
            return {
                "status": "AWAITING_MODEL_AUDIT",
                "task_id": "task_original",
                "execution_id": "original_execution",
                "audit_id": "original_audit",
            }
        if command == "audit-openai-doctor":
            return {
                "status": "READY",
                "available_cents": ledger.available(),
                "pricing": {
                    "model": "gpt-6.1-sol",
                    "input_token_ceiling": 1050000,
                    "output_token_limit": 1200,
                    "maximum_cents": 1808,
                },
            }
        assert command == "flow1-billing-cycle" and options[0] == call_id
        result = billing.reconcile(
            ledger, call_id, project="proj_fixture", admin=True, snapshots=True, apply=True
        )
        return {
            "status": "WAITING_BILLING"
            if result["ledger_status"] != "SETTLED"
            else "READY_FOR_AUDITOR_PREFLIGHT",
            "billing": result,
        }

    def publish():
        nonlocal published
        published = True

    return path, config, ledger, created, call_id, usage, execute, publish, invocations


def test_wait_over_six_hours_midnight_restart_and_single_charge(worker):
    _, config, ledger, created, _, _, execute, publish, invocations = worker
    future = created + timedelta(days=1, hours=7)
    assert tick(config, execute=execute, now=future)["dossiers"][0]["status"] == "WAITING_BILLING"
    assert tick(config, execute=execute, now=future)["dossiers"][0]["status"] == "NOT_DUE"
    publish()
    assert (
        tick(config, execute=execute, now=future + timedelta(minutes=5))["dossiers"][0]["status"]
        == "AUDITOR_AUTHORIZATION_REQUIRED"
    )
    assert len(ledger.inspect()["calls"]) == 1 and ledger.available() == 1999
    assert (
        tick(config, execute=execute, now=future + timedelta(minutes=10))["dossiers"][0]["status"]
        == "AUDITOR_AUTHORIZATION_REQUIRED"
    )
    assert ledger.available() == 1999 and "audit-openai" not in invocations


def test_ambiguous_and_expired_require_review(worker):
    _, config, ledger, created, _, usage, execute, _, _ = worker
    usage["num_model_requests"] = 2
    assert (
        tick(config, execute=execute, now=created + timedelta(hours=7))["dossiers"][0]["status"]
        == "REVIEW_REQUIRED"
    )
    with pytest.raises(ValueError, match="UNKNOWN_API_SPEND"):
        ledger.available()
    assert (
        tick(config, execute=execute, now=created + timedelta(hours=8))["dossiers"][0]["status"]
        == "REVIEW_REQUIRED"
    )
    state = Path(config["state_directory"]) / (
        digest(str(Path(config["dossiers"][0]).resolve())) + ".json"
    )
    state.unlink()  # Explicit operator reset in this isolated test.
    assert (
        tick(config, execute=execute, now=created + timedelta(hours=49))["dossiers"][0]["reason"]
        == "Reservation outside maximum age"
    )


def test_interruption_after_settlement_resumes_without_second_release(worker):
    path, config, ledger, created, _, _, execute, publish, _ = worker
    publish()

    def interrupted(database, command, *options, timeout):
        result = execute(database, command, *options, timeout=timeout)
        if command == "flow1-billing-cycle":
            raise KeyboardInterrupt
        return result

    with pytest.raises(KeyboardInterrupt):
        tick(config, execute=interrupted, now=created + timedelta(hours=7))
    assert ledger.available() == 1999
    restarted = subprocess.run(
        [sys.executable, "-B", "scripts/poll_flow1_billing.py", "--config", str(path)],
        capture_output=True,
        check=True,
        timeout=30,
    )
    assert json.loads(restarted.stdout)["dossiers"][0]["status"] == "NOT_DUE"
    assert (
        tick(config, execute=execute, now=created + timedelta(hours=7, minutes=5))["dossiers"][0][
            "status"
        ]
        == "AUDITOR_AUTHORIZATION_REQUIRED"
    )
    assert ledger.available() == 1999


def test_two_processes_share_the_ledger_worker_lock(worker):
    path, config, *_ = worker
    lock = Path(config["ledger"]).with_suffix(".flow1-billing-worker.lock")
    with coordinator_lock(lock):
        result = subprocess.run(
            [sys.executable, "-B", "scripts/poll_flow1_billing.py", "--config", str(path)],
            capture_output=True,
            check=True,
            timeout=30,
        )
    assert json.loads(result.stdout)["status"] == "BUSY"


def test_interrupted_auditor_reservation_cannot_dispatch_twice(worker):
    _, config, ledger, created, _, _, execute, publish, _ = worker
    config["allow_model_audit"] = True
    publish()
    dispatched = []

    def dispatch(database, command, *options, timeout):
        if command == "audit-openai":
            assert options[-3:] == ("--billing-scope", "org-fixture", "proj_fixture")
            dispatched.append(
                ledger.reserve("openai", "openai-audit-v1:original_execution", 1808, once=True)
            )
            raise KeyboardInterrupt
        return execute(database, command, *options, timeout=timeout)

    now = created + timedelta(hours=7)
    with pytest.raises(KeyboardInterrupt):
        tick(config, execute=dispatch, now=now)
    result = tick(config, execute=dispatch, now=now + timedelta(minutes=5))["dossiers"][0]
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["reason"] == "Provider outcome requires reconciliation"
    assert len(dispatched) == 1 and len(ledger.inspect()["calls"]) == 2
    with pytest.raises(ValueError, match="UNKNOWN_API_SPEND"):
        ledger.available()
