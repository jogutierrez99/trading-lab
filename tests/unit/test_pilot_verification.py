"""4.5 isolated recovery/query tests. No real models, backtests or Telegram.

Reuses 4.4's artificial receipt fixture, which explicitly simulates the inherited
implementation seal checks. The real pilot is separately checked without mocks.
"""

import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_audit_orchestration import Transport, fixture

from trading_lab_orchestration.audit_notifications import Outbox, Outcome
from trading_lab_orchestration.cli import main
from trading_lab_orchestration.contracts import HypothesisManifest, canonical
from trading_lab_orchestration.execution import Executor
from trading_lab_orchestration.implementation import Coordinator
from trading_lab_orchestration.implementation_contracts import (
    ImplementationPlan,
    ImplementationRequest,
)
from trading_lab_orchestration.pilot import PilotVerifier, export_pilot
from trading_lab_orchestration.pilot_contracts import PilotVerificationRequest
from trading_lab_orchestration.readonly import ReadOnlyStore
from trading_lab_orchestration.store import Store
from trading_lab_orchestration.workspaces import file_hash, inventory, write_json

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def pilot(tmp_path, monkeypatch):
    base = fixture.__wrapped__(tmp_path, monkeypatch)
    state = base.store.show(base.request.task_id)
    manifest = HypothesisManifest.model_validate_json(canonical(state["manifest"]))
    source = tmp_path / "source"
    plan = ImplementationPlan(
        schema_version="1.0",
        operation="NEW_STRATEGY",
        target="fixture",
        specification_reviewed=True,
        review_note="Simulated verification source",
        max_wall_seconds=120,
        check_timeout_seconds=30,
    )
    with base.store.transaction() as c:
        c.execute("UPDATE candidates SET status='IMPLEMENTATION_READY'")
        c.execute("UPDATE tasks SET status='SUCCEEDED',kind='IMPLEMENTATION'")
        c.execute("UPDATE attempts SET number=3")
        for number in (1, 2, 3):
            identifier = "attempt_fixture" if number == 3 else "attempt_prior_" + str(number)
            directory = source if number == 3 else tmp_path / ("prior" + str(number))
            directory.mkdir(exist_ok=True)
            request = ImplementationRequest(
                schema_version="1.0",
                mode="PREPARE_ONLY",
                attempt_id=identifier,
                attempt_number=number,
                task_id=base.request.task_id,
                candidate_id=state["candidate_id"],
                hypothesis_manifest=manifest,
                hypothesis_sha256=state["manifest_sha256"],
                base_commit="0" * 40,
                branch="fixture",
                workspace=str(directory),
                plan=plan,
                allowed_write_paths=[],
                protected_paths=[],
                authorized_checks=[],
                skill_paths=[],
                previous_attempt=None,
                max_api_eur=None,
                max_cpu_seconds=None,
            )
            write_json(directory / "request.json", request.model_dump(mode="json"))
            if number == 3:
                c.execute(
                    "UPDATE attempts SET request_sha256=? WHERE attempt_id=?",
                    (file_hash(directory / "request.json"), identifier),
                )
            else:
                c.execute(
                    "INSERT INTO attempts(attempt_id,task_id,number,status,repo,root,workspace,"
                    "branch,base_commit,request_sha256,created_at_utc) "
                    "VALUES(?,?,?,'FAILED',?,?,?,'fixture',?,?,'fixture')",
                    (
                        identifier,
                        base.request.task_id,
                        number,
                        str(directory),
                        str(directory),
                        str(directory),
                        "0" * 40,
                        file_hash(directory / "request.json"),
                    ),
                )
        for entity, old, new in (
            ("candidate", "HYPOTHESIS_READY", "IMPLEMENTATION_READY"),
            ("task", "QUEUED", "SUCCEEDED"),
        ):
            base.store._event(
                c,
                state["candidate_id"],
                base.request.task_id,
                entity,
                old,
                new,
                "Simulated source history",
                {},
                actor="simulated_fixture",
            )
    audit = base.auditor.run(base.request, base.output)
    assert audit["status"] == "COMPLETED_WITH_LIMITATIONS"
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setenv("TRADING_LAB_TELEGRAM_VERIFIED_PRIVATE_CHAT_ID", "12345")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:SIMULATED_SECRET")
    box = Outbox(base.store)
    draft = box.preview(audit["audit_id"])
    sent = box.send(
        draft["notification_id"],
        transport=Transport(Outcome("ACCEPTED", "TELEGRAM_SERVICE_ACCEPTED", 42)),
    )
    receipt = tmp_path / "delivery/receipt.json"
    receipt.parent.mkdir()
    write_json(
        receipt,
        {
            "schema_version": "1.0",
            "kind": "ManualTelegramAcceptance",
            "audit_id": audit["audit_id"],
            "notification_id": sent["notification_id"],
            "status": "ACCEPTED",
            "attempts": 1,
            "message_id": 42,
            "outcome": sent["outcome"],
            "message_sha256": sent["message_sha256"],
            "private_chat_verified": True,
            "service_acceptance_is_not_read_receipt": True,
        },
    )
    base.pilot_request = PilotVerificationRequest(
        task_id=base.request.task_id,
        implementation_id="attempt_fixture",
        execution_id="execution_fixture",
        run_id="run_fixed",
        audit_id=audit["audit_id"],
        notification_id=sent["notification_id"],
        strategy="fixture",
        strategy_version="1.0.1",
        telegram_receipt=str(receipt),
        telegram_receipt_sha256=file_hash(receipt),
        expected_message_id=42,
    )
    base.parent = tmp_path

    def forbidden(*args, **kwargs):
        raise AssertionError("No model, runner or network operation is allowed")

    monkeypatch.setattr(Coordinator, "run", forbidden)
    monkeypatch.setattr(Executor, "run", forbidden)
    monkeypatch.setattr("socket.create_connection", forbidden)
    return base


def verify(pilot):
    return PilotVerifier(pilot.store.path).verify(pilot.pilot_request)


def test_success_repeat_and_no_operational_changes(pilot):
    before = inventory(pilot.parent)
    first, second = verify(pilot), verify(pilot)
    assert first.status == second.status == "VERIFIED_HISTORICAL_TECHNICAL_PILOT"
    assert all(s.status == "VERIFIED" for s in first.stages.values())
    assert first.candidate_id == pilot.request.candidate_id
    assert first.historical_reconstruction and not first.new_end_to_end_execution
    assert not first.unattended_automation and not first.model_auditor_deployed
    assert not first.economic_validation and not first.demo_authorized
    assert inventory(pilot.parent) == before
    assert "SIMULATED_SECRET" not in first.model_dump_json()


def test_two_successful_concurrent_queries(pilot):
    before = inventory(pilot.parent)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: verify(pilot), range(2)))
    assert all(r.status == "VERIFIED_HISTORICAL_TECHNICAL_PILOT" for r in results)
    assert inventory(pilot.parent) == before


def test_interruption_is_repeatable_without_effects(pilot, monkeypatch):
    import trading_lab_orchestration.pilot as module

    original = module.review
    before = inventory(pilot.parent)

    def interrupt(*args):
        raise KeyboardInterrupt()

    monkeypatch.setattr(module, "review", interrupt)
    with pytest.raises(KeyboardInterrupt):
        verify(pilot)
    assert inventory(pilot.parent) == before
    monkeypatch.setattr(module, "review", original)
    assert verify(pilot).status == "VERIFIED_HISTORICAL_TECHNICAL_PILOT"


@pytest.mark.parametrize(
    "incident",
    [
        "altered",
        "missing",
        "other_implementation",
        "audit_report",
        "telegram_receipt",
        "wrong_message",
        "execution_unknown",
        "telegram_unknown",
        "telegram_sending",
        "attempt_unknown",
        "source_request",
        "attempt_unpinned",
    ],
)
def test_incidents_block_without_changing_history(pilot, incident):
    if incident == "altered":
        (pilot.run / "summary.json").write_text("{}")
    elif incident == "missing":
        (pilot.run / "outcome.json").unlink()
    elif incident == "other_implementation":
        pilot.pilot_request = pilot.pilot_request.model_copy(
            update={"implementation_id": "attempt_other"}
        )
    elif incident == "audit_report":
        audit = pilot.auditor.get(pilot.pilot_request.audit_id)
        (Path(audit["root"]) / "audit_report.md").write_text("altered")
    elif incident == "telegram_receipt":
        Path(pilot.pilot_request.telegram_receipt).write_text("{}")
    elif incident == "source_request":
        (pilot.parent / "prior1/request.json").write_text("{}")
    else:
        with pilot.store.transaction() as c:
            if incident == "wrong_message":
                c.execute("UPDATE audit_outbox SET message_id=99")
            elif incident == "execution_unknown":
                c.execute("UPDATE executions SET status='UNKNOWN'")
            elif incident == "attempt_unknown":
                c.execute("UPDATE attempts SET status='UNKNOWN' WHERE number=3")
            elif incident == "attempt_unpinned":
                c.execute("UPDATE attempts SET request_sha256=NULL WHERE number=1")
            else:
                c.execute(
                    "UPDATE audit_outbox SET status=?",
                    ("UNKNOWN" if incident == "telegram_unknown" else "SENDING",),
                )
    before = inventory(pilot.parent)
    result = verify(pilot)
    assert result.status == "BLOCKED"
    assert inventory(pilot.parent) == before
    if incident in {"telegram_unknown", "telegram_sending"}:
        assert "reconciliation required" in result.stages["telegram"].evidence[0]
    if incident == "execution_unknown":
        assert "never relaunch" in result.stages["execution"].evidence[0]


def test_readonly_store_reuses_snapshot_and_refuses_writes(pilot):
    before = file_hash(pilot.store.path)
    with ReadOnlyStore(pilot.store.path).snapshot() as store:
        assert store.show(pilot.request.task_id) == store.show(pilot.request.task_id)
        with pytest.raises(ValueError, match="prohibits"):
            store.transaction()
        with store.connection() as c, pytest.raises(sqlite3.OperationalError):
            c.execute("UPDATE tasks SET status='FAILED'")
    assert file_hash(pilot.store.path) == before


def test_wrong_schema_is_not_migrated(pilot):
    with pilot.store.transaction() as c:
        c.execute("PRAGMA user_version=4")
    before = file_hash(pilot.store.path)
    result = verify(pilot)
    assert result.status == "BLOCKED"
    assert "no migration" in result.stages["intake"].evidence[0]
    assert file_hash(pilot.store.path) == before


def test_missing_database_does_not_create_it(pilot):
    missing = pilot.parent / "absent/db.sqlite"
    result = PilotVerifier(missing).verify(pilot.pilot_request)
    assert result.status == "BLOCKED"
    assert not missing.parent.exists()


def test_export_separate_and_immutable(pilot):
    result = verify(pilot)
    with pytest.raises(ValueError, match="outside"):
        export_pilot(result, pilot.root)
    before = inventory(pilot.parent)
    exported = export_pilot(result, pilot.parent / "exports")
    root = Path(exported["directory"])
    assert json.loads((root / "pilot_verification.json").read_text())["schema_version"] == "1.0"
    assert "Intervención manual" in (root / "pilot_report.md").read_text(encoding="utf-8")
    assert all(file_hash(pilot.parent / k) == sha for k, sha in before.items())
    with pytest.raises(FileExistsError):
        export_pilot(result, pilot.parent / "exports")


def test_blocked_query_cannot_export_into_inspected_execution(pilot):
    (pilot.parent / "prior1/request.json").write_text("{}")
    result = verify(pilot)
    assert result.status == "BLOCKED"
    before = inventory(pilot.parent)
    with pytest.raises(ValueError, match="outside"):
        export_pilot(result, pilot.root)
    assert inventory(pilot.parent) == before


def test_cli_json_text_and_no_store_initialization(pilot, monkeypatch, capsys):
    request_file = pilot.parent / "query.json"
    request_file.write_text(pilot.pilot_request.model_dump_json())

    def forbidden(*args):
        raise AssertionError("Writable Store constructor called")

    monkeypatch.setattr(Store, "__init__", forbidden)
    args = ["--db", str(pilot.store.path), "verify-pilot", str(request_file)]
    before = inventory(pilot.parent)
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "VERIFIED_HISTORICAL_TECHNICAL_PILOT"
    assert main(args + ["--format", "text"]) == 0
    assert "cierre del piloto histórico" in capsys.readouterr().out
    assert inventory(pilot.parent) == before


def test_invalid_request_does_not_create_database(pilot, capsys):
    request_file = pilot.parent / "invalid.json"
    request_file.write_text("{}")
    missing = pilot.parent / "absent/db.sqlite"
    assert main(["--db", str(missing), "verify-pilot", str(request_file)]) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "INVALID_PILOT_REQUEST"
    assert not missing.parent.exists()
    with pytest.raises(ValidationError):
        PilotVerificationRequest.model_validate(
            pilot.pilot_request.model_dump() | {"audit_id": "latest"}
        )


def test_cli_keeps_versioned_blocked_result_when_safe_export_is_unavailable(pilot, capsys):
    (pilot.root / "request.json").unlink()
    request = pilot.parent / "query.json"
    request.write_text(pilot.pilot_request.model_dump_json())
    output = pilot.parent / "exports"
    before = inventory(pilot.parent)
    code = main(
        ["--db", str(pilot.store.path), "verify-pilot", str(request), "--output", str(output)]
    )
    result = json.loads(capsys.readouterr().out)
    assert code == 2 and result["schema_version"] == "1.0" and result["status"] == "BLOCKED"
    assert "export_error" in result and not output.exists()
    assert inventory(pilot.parent) == before


def test_two_cli_processes_cannot_modify_fixture_without_source_seals(pilot):
    request_file = pilot.parent / "query.json"
    request_file.write_text(pilot.pilot_request.model_dump_json())
    before = inventory(pilot.parent)
    args = [
        sys.executable,
        "-B",
        str(ROOT / "scripts/orchestrator.py"),
        "--db",
        str(pilot.store.path),
        "verify-pilot",
        str(request_file),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    processes = [
        subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        for _ in range(2)
    ]
    for p in processes:
        stdout, stderr = p.communicate(timeout=30)
        # A new process does not inherit simulated implementation seal checks.
        assert p.returncode == 2 and json.loads(stdout)["status"] == "BLOCKED"
        assert b"Traceback" not in stderr
    assert inventory(pilot.parent) == before
