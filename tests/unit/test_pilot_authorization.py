import json
import runpy
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from trading_lab_orchestration import implementation
from trading_lab_orchestration import pilot_authorization as auth
from trading_lab_orchestration.audit_model import Budget
from trading_lab_orchestration.contracts import canonical, digest
from trading_lab_orchestration.github_intake import consume
from trading_lab_orchestration.implementation import Coordinator, load_plan
from trading_lab_orchestration.store import Store
from trading_lab_orchestration.workspaces import git

ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "examples/orchestration/phase-5-4b"
OPERATOR = ("test\\operator", "S-1-5-21-1000")


def stub_workspace(attempt, paths):
    Path(attempt["workspace"]).mkdir()
    (Path(attempt["root"]) / "baseline.json").write_text("{}", encoding="utf-8")
    for target in paths:
        path = Path(attempt["workspace"]) / target
        path.parent.mkdir(parents=True, exist_ok=True)
        content = f"name: {path.stem}\nenabled: false\n" if path.suffix == ".yaml" else "scaffold"
        path.write_text(content, encoding="utf-8")


def stub_scaffold(argv, *args, **kwargs):
    assert argv[1] == "scripts/create_strategy.py"
    return {"exit_code": 0, "timed_out": False}


def stub_changes(attempt):
    workspace = Path(attempt["workspace"])
    return {
        p.relative_to(workspace).as_posix(): digest(p.read_text(encoding="utf-8"))
        for p in workspace.rglob("*")
        if p.is_file()
    }


@pytest.fixture
def case(tmp_path, monkeypatch):
    repo = tmp_path / "git"
    repo.mkdir()
    git(repo, "init")
    git(repo, "remote", "add", "origin", "https://github.com/jogutierrez99/trading-lab.git")
    db = tmp_path / "queue.sqlite3"
    ledger = Budget(Store(tmp_path / "ledger.sqlite3"))
    ledger.open_month(0, "Isolated test")
    config = repo / "examples/orchestration/flow1_billing_worker.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"ledger": str(ledger.store.path)}), encoding="utf-8")
    git(repo, "add", "--", config.relative_to(repo).as_posix())
    git(
        repo,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "fixture",
    )
    issue = {
        "id": 1234,
        "number": 3,
        "user": {"id": auth.DEFAULT_AUTHOR_ID},
        "state": "open",
        "html_url": "https://github.com/jogutierrez99/trading-lab/issues/3",
        "labels": [{"name": "strategy-intake"}],
        "body": (PILOT / "issue-body.json").read_text(encoding="utf-8"),
    }
    (admission,) = consume(db, {auth.DEFAULT_AUTHOR_ID}, lambda: [issue], source_mode="GITHUB")[
        "issues"
    ]
    assert admission["status"] == "ACCEPTED"
    plan = load_plan(PILOT / "implementation-plan.draft.json")
    receipt = auth.PreparationAuthorization(
        schema_version="1.0",
        repository="jogutierrez99/trading-lab",
        issue_number=3,
        issue_id=1234,
        task_id=admission["task_id"],
        proposal_sha256=admission["proposal_sha256"],
        plan_sha256=digest(canonical(plan.model_dump(mode="json"))),
        permission="PREPARE_ONLY",
        operation="NEW_STRATEGY",
        approved_by=OPERATOR[0],
        operator_sid=OPERATOR[1],
        approved_at_utc=datetime.now(UTC),
        body_sha256=digest(issue["body"]),
        base_commit=git(repo, "rev-parse", "HEAD"),
        ledger_path=str(ledger.store.path),
        max_wall_seconds=plan.max_wall_seconds,
        check_timeout_seconds=plan.check_timeout_seconds,
    )
    monkeypatch.setattr(auth, "current_operator", lambda: OPERATOR)
    monkeypatch.setattr(auth, "read_token", lambda _: "simulated")
    monkeypatch.setattr(auth, "fetch_issue", lambda *_: [issue])
    monkeypatch.setattr(implementation, "create_workspace", stub_workspace)
    monkeypatch.setattr(implementation, "run_process", stub_scaffold)
    monkeypatch.setattr(implementation, "changes", stub_changes)
    monkeypatch.setattr(implementation, "CodexCLI", lambda *a, **kw: pytest.fail("Codex invoked"))
    return Coordinator(Store(db)), ledger, repo, issue, plan, receipt


def grant(case, receipt=None, plan=None):
    coordinator, ledger, repo, _, original_plan, original = case
    with coordinator.store.transaction() as conn:
        return auth._persist_authorization(
            conn, receipt or original, plan or original_plan, repo, ledger.store.path
        )


def prepare(case, auth_id, *, plan=None, issue=None):
    coordinator, _, repo, original_issue, original_plan, receipt = case
    with patch.object(auth, "fetch_issue", return_value=[issue or original_issue]):
        return coordinator.prepare(
            receipt.task_id,
            repo,
            repo.parent / "artifacts",
            plan or original_plan,
            pilot=auth.PilotPreparation(auth_id, None),
        )


def state(case, auth_id):
    with case[0].store.connection() as conn:
        row, _ = auth.authorization(conn, auth_id)
        count = conn.execute("SELECT count(*) FROM attempts").fetchone()[0]
        return row["state"], count


def test_use_once_and_launch_remains_blocked(case):
    coordinator, ledger, repo, _, plan, receipt = case
    initial = ledger.store.path.read_bytes()
    with pytest.raises(ValueError, match="PREPARATION_NOT_ENABLED"):
        coordinator.prepare(receipt.task_id, repo, repo.parent / "artifacts", plan)
    with pytest.raises(ValueError, match="AUTHORIZATION_REQUIRED"):
        prepare(case, "absent")
    auth_id = grant(case)
    with pytest.raises(ValueError, match="already exists"):
        grant(case)
    result = prepare(case, auth_id)
    assert result["status"] == "PREPARED" and state(case, auth_id) == ("CONSUMED", 1)
    with pytest.raises(ValueError, match="AUTHORIZATION_UNAVAILABLE"):
        prepare(case, auth_id)
    with pytest.raises(ValueError, match="LAUNCH_AUTHORIZATION_NOT_ENABLED"):
        coordinator.run(result["attempt_id"])
    with pytest.raises(ValueError, match="LAUNCH_AUTHORIZATION_NOT_ENABLED"):
        coordinator.reconcile(result["attempt_id"], "verify", True, "fixture")
    with (
        pytest.raises(sqlite3.IntegrityError, match="no launch authorization"),
        coordinator.store.transaction() as conn,
    ):
        conn.execute(
            "UPDATE attempts SET status='RUNNING' WHERE attempt_id=?", (result["attempt_id"],)
        )
    assert state(case, auth_id) == ("CONSUMED", 1)
    assert ledger.store.path.read_bytes() == initial


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("proposal_sha256", "0" * 64),
        ("plan_sha256", "0" * 64),
        ("base_commit", "0" * 40),
        ("task_id", "another_task"),
        ("issue_id", 9912),
        ("operator_sid", "S-1-5-21-1111"),
    ],
)
def test_invalid_binding(case, field, value):
    receipt = case[-1].model_copy(update={field: value})
    with pytest.raises(ValueError):
        grant(case, receipt=receipt)
    assert not (case[2].parent / "artifacts").exists()


def test_recheck_plan_base_live_issue_and_operator_at_consumption(case, monkeypatch):
    auth_id = grant(case)
    with pytest.raises(ValueError, match="BINDING_MISMATCH"):
        prepare(case, auth_id, plan=case[-2].model_copy(update={"max_wall_seconds": 59}))
    with pytest.raises(ValueError, match="Live Issue differs"):
        prepare(case, auth_id, issue=case[3] | {"state": "closed"})
    with monkeypatch.context() as changed:
        changed.setattr(auth, "current_operator", lambda: (OPERATOR[0], "S-1-5-21-2000"))
        with pytest.raises(ValueError, match="OPERATOR_MISMATCH"):
            prepare(case, auth_id)
    git(
        case[2],
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "changed base",
    )
    with pytest.raises(ValueError, match="BINDING_MISMATCH"):
        prepare(case, auth_id)
    assert state(case, auth_id) == ("APPROVED", 0)


@pytest.mark.parametrize("blocker", ["budget", "unavailable", "reserved", "prior", "uncertain"])
def test_recheck_preparation_gates(case, blocker):
    coordinator, ledger, repo, _, _, receipt = case
    auth_id = grant(case)
    prior_count = 0
    if blocker == "budget":
        with ledger.store.transaction() as conn:
            conn.execute("UPDATE api_months SET opening_spend_cents=2000")
    elif blocker == "unavailable":
        ledger.store.path.rename(ledger.store.path.with_suffix(".unavailable"))
    elif blocker == "reserved":
        ledger.reserve("test", "mock pending", 1)
    else:
        prior_count = 1
        task_id = receipt.task_id
        if blocker == "uncertain":
            from trading_lab_orchestration.contracts import HypothesisManifest
            from trading_lab_orchestration.github_intake import parse_proposal

            original = parse_proposal(case[3]["body"]).manifest.model_dump(mode="json")
            original.update(hypothesis_id="another_task", market_hypothesis="Different strategy")
            original["signal_spec"]["long_entry"] = "Different signal"
            task_id = coordinator.store.register(
                HypothesisManifest.model_validate_json(canonical(original))
            )["task_id"]
        with coordinator.store.transaction() as conn:
            conn.execute(
                """INSERT INTO attempts (
                attempt_id,task_id,number,status,repo,root,workspace,branch,base_commit,created_at_utc
                ) VALUES ('prior',?,1,?,'repo','root','workspace','branch',?,'fixture')""",
                (
                    task_id,
                    "UNKNOWN" if blocker == "uncertain" else "CANCELLED",
                    receipt.base_commit,
                ),
            )
    with pytest.raises((ValueError, FileNotFoundError)):
        prepare(case, auth_id)
    assert state(case, auth_id) == ("APPROVED", prior_count)
    assert not (repo.parent / "artifacts").exists()


def test_plan_incompatible(case):
    plan = case[-2].model_copy(update={"operation": "NEW_EXPERIMENT"})
    receipt = case[-1].model_copy(
        update={"plan_sha256": digest(canonical(plan.model_dump(mode="json")))}
    )
    with pytest.raises(ValueError, match="BINDING_MISMATCH"):
        grant(case, receipt=receipt, plan=plan)


def test_substitute_ledger_cannot_be_approved(case, tmp_path):
    coordinator, _, repo, _, plan, receipt = case
    alternate = Budget(Store(tmp_path / "alternate.sqlite3"))
    alternate.open_month(0, "Substitution fixture")
    receipt = receipt.model_copy(update={"ledger_path": str(alternate.store.path)})
    with (
        pytest.raises(ValueError, match="canonical path"),
        coordinator.store.transaction() as conn,
    ):
        auth._persist_authorization(conn, receipt, plan, repo, alternate.store.path)


def test_published_issue_cannot_be_rebound_to_another_task(case):
    coordinator, _, _, _, _, receipt = case
    with coordinator.store.transaction() as conn:
        conn.execute("UPDATE github_intake SET issue_id=6429388150 WHERE issue_number=3")
    with pytest.raises(ValueError, match="original queued task"):
        grant(case, receipt=receipt.model_copy(update={"issue_id": 6429388150}))


def test_budget_snapshot_prevents_writer_commit_before_reservation(case):
    coordinator, ledger, *_ = case
    path = ledger.store.path
    writer = sqlite3.connect(path, timeout=0)
    try:
        with auth.budget_guard(coordinator.store.path, path):
            writer.execute("UPDATE api_months SET opening_spend_cents=2000")
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                writer.commit()
        writer.commit()
        assert ledger.available() == 0
    finally:
        writer.close()


def test_enabled_profile_cannot_complete_preparation(case, monkeypatch):
    auth_id = grant(case)

    def enabled(attempt, paths):
        stub_workspace(attempt, paths)
        path = Path(attempt["workspace"]) / paths[1]
        path.write_text(f"name: {path.stem}\nenabled: true\n", encoding="utf-8")

    monkeypatch.setattr(implementation, "create_workspace", enabled)
    result = prepare(case, auth_id)
    assert result["status"] == "UNKNOWN" and "remain disabled" in result["error"]
    assert state(case, auth_id) == ("UNKNOWN", 1)


def test_interruption_never_reuses_attempt(case, monkeypatch):
    auth_id = grant(case)

    def interrupt(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(implementation, "create_workspace", interrupt)
    with pytest.raises(KeyboardInterrupt):
        prepare(case, auth_id)
    assert state(case, auth_id) == ("UNKNOWN", 1)
    with pytest.raises(ValueError, match="AUTHORIZATION_UNAVAILABLE"):
        prepare(case, auth_id)
    c = Coordinator(Store(case[0].store.path))
    with pytest.raises(ValueError, match="stopped confirmation"):
        c.close_pilot_preparation(auth_id, "preserve evidence")
    assert (
        c.close_pilot_preparation(auth_id, "Test operator verified no child", confirm_stopped=True)[
            "status"
        ]
        == "CANCELLED"
    )
    assert state(case, auth_id) == ("CLOSED", 1)
    with pytest.raises(ValueError, match="already has an attempt"):
        grant(case)


WORKER = """
import json, os, runpy, sys, time
from pathlib import Path
from trading_lab_orchestration import implementation, pilot_authorization as auth
from trading_lab_orchestration.implementation import Coordinator, load_plan
from trading_lab_orchestration.store import Store
module=runpy.run_path(sys.argv[1])
spec=json.loads(Path(sys.argv[2]).read_bytes())
auth.current_operator=lambda: module["OPERATOR"]
auth.read_token=lambda _: "simulated"
auth.fetch_issue=lambda *_: [spec["issue"]]
implementation.create_workspace=module["stub_workspace"]
if spec.get("crash"):
    implementation.create_workspace=lambda *_: os._exit(77)
implementation.run_process=module["stub_scaffold"]
implementation.changes=module["stub_changes"]
coordinator=Coordinator(Store(Path(spec["db"])))
while not Path(spec["start"]).exists():
    time.sleep(0.01)
try:
    result=coordinator.prepare(
        spec["task_id"],Path(spec["repo"]),Path(spec["artifacts"]),load_plan(Path(spec["plan"])),
        pilot=auth.PilotPreparation(spec["auth_id"],None),
    )
    print(result["status"])
except ValueError as exc:
    print("BLOCKED", exc)
"""


def worker_args(case, tmp_path, *, crash=False):
    c, _, repo, issue, _, receipt = case
    auth_id = grant(case)
    flag = tmp_path / "start"
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            dict(
                db=str(c.store.path),
                repo=str(repo),
                start=str(flag),
                artifacts=str(tmp_path / "outputs"),
                plan=str(PILOT / "implementation-plan.draft.json"),
                auth_id=auth_id,
                task_id=receipt.task_id,
                issue=issue,
                crash=crash,
            )
        ),
        encoding="utf-8",
    )
    return auth_id, flag, [sys.executable, "-B", "-c", WORKER, __file__, str(spec)]


def test_two_processes_reserve_once(case, tmp_path):
    auth_id, flag, args = worker_args(case, tmp_path)
    with (
        subprocess.Popen(args, stdout=subprocess.PIPE, text=True) as first,
        subprocess.Popen(args, stdout=subprocess.PIPE, text=True) as second,
    ):
        flag.touch()
        results = [process.communicate(timeout=20)[0].strip() for process in (first, second)]
    assert results.count("PREPARED") == 1
    assert len([r for r in results if r.startswith("BLOCKED")]) == 1
    assert state(case, auth_id) == ("CONSUMED", 1)


def test_abrupt_exit_persists_reservation_for_reconciliation(case, tmp_path):
    auth_id, flag, args = worker_args(case, tmp_path, crash=True)
    flag.touch()
    result = subprocess.run(args, capture_output=True, timeout=20)
    assert result.returncode == 77, result.stderr
    assert state(case, auth_id) == ("RESERVED", 1)
    with pytest.raises(ValueError, match="AUTHORIZATION_UNAVAILABLE"):
        prepare(case, auth_id)
    assert (
        case[0].close_pilot_preparation(
            auth_id, "Offline fixture verified stopped", confirm_stopped=True
        )["status"]
        == "CANCELLED"
    )
    assert state(case, auth_id) == ("CLOSED", 1)


def test_approval_cli_rejects_redirected_input_without_registering(case):
    c, ledger, repo, _, _, receipt = case
    initial = c.store.path.read_bytes()
    args = [
        sys.executable,
        "-B",
        str(ROOT / "scripts/authorize_github_pilot.py"),
        "--db",
        str(c.store.path),
        "approve",
        "--repo",
        str(repo),
        "--ledger",
        str(ledger.store.path),
        "--plan",
        str(PILOT / "implementation-plan.draft.json"),
        "--issue",
        "3",
        "--issue-id",
        str(receipt.issue_id),
        "--task-id",
        receipt.task_id,
        "--base-commit",
        receipt.base_commit,
        "--body-sha256",
        receipt.body_sha256,
        "--proposal-sha256",
        receipt.proposal_sha256,
        "--plan-sha256",
        receipt.plan_sha256,
    ]
    result = subprocess.run(args, input="approval\n", text=True, capture_output=True, timeout=20)
    assert result.returncode == 2 and "interactive Windows terminal" in result.stdout
    assert c.store.path.read_bytes() == initial


def test_interactive_cli_records_token_identity_after_exact_confirmation(case, monkeypatch):
    c, ledger, repo, _, _, receipt = case
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    run = runpy.run_path(str(ROOT / "scripts/authorize_github_pilot.py"))["_run"]
    tty = SimpleNamespace(isatty=lambda: True)
    monkeypatch.setitem(run.__globals__, "sys", SimpleNamespace(stdin=tty, stdout=tty))
    monkeypatch.setattr(auth, "sys", SimpleNamespace(stdin=tty, stdout=tty))
    args = SimpleNamespace(
        command="approve",
        db=c.store.path,
        ledger=ledger.store.path,
        repo=repo,
        plan=PILOT / "implementation-plan.draft.json",
        env_file=None,
        issue=receipt.issue_number,
        issue_id=receipt.issue_id,
        task_id=receipt.task_id,
        proposal_sha256=receipt.proposal_sha256,
        plan_sha256=receipt.plan_sha256,
        body_sha256=receipt.body_sha256,
        base_commit=receipt.base_commit,
    )
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    before = c.store.path.read_bytes()
    with pytest.raises(ValueError, match="confirmation did not match"):
        run(args)
    assert before == c.store.path.read_bytes()
    monkeypatch.setattr(
        "builtins.input", lambda _: f"AUTORIZAR {receipt.task_id} {receipt.base_commit}"
    )
    result = run(args)
    with c.store.connection() as conn:
        row, grant = auth.authorization(conn, result["authorization_id"])
        assert row["state"] == "APPROVED" and row["attempt_id"] is None
        assert (grant.approved_by, grant.operator_sid) == OPERATOR
