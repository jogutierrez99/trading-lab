import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from trading_lab_orchestration import github_review
from trading_lab_orchestration.audit_model import Budget
from trading_lab_orchestration.contracts import canonical, digest
from trading_lab_orchestration.github_intake import consume
from trading_lab_orchestration.github_review import (
    DEFAULT_AUTHOR_ID,
    ReviewAuthorization,
    diagnose_issue,
)
from trading_lab_orchestration.implementation import Coordinator
from trading_lab_orchestration.implementation_contracts import ImplementationPlan
from trading_lab_orchestration.processes import coordinator_lock
from trading_lab_orchestration.store import Store

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Review must stay read-only and offline")

    for name in ("prepare", "run"):
        monkeypatch.setattr(Coordinator, name, forbidden)
    monkeypatch.setattr("http.client.HTTPSConnection", forbidden)
    (issue,) = json.loads(
        (ROOT / "examples/orchestration/github_strategy_issue_fixture.json").read_bytes()
    )
    issue["user"]["id"] = DEFAULT_AUTHOR_ID
    body = json.loads(issue["body"])
    body["manifest"]["data_requirements"]["availability"] = "MANUALLY_VERIFIED"
    body["manifest"]["evaluation_plan"]["holdout_status"] = "UNOBSERVED_DECLARED"
    ledger = Budget(Store(tmp_path / "ledger.sqlite3"))
    ledger.open_month(0, "Isolated test")
    return tmp_path / "queue.sqlite3", ledger, issue, body


def register(db, issue, body):
    result = consume(
        db,
        {DEFAULT_AUTHOR_ID},
        lambda: [issue | {"body": canonical(body)}],
        source_mode="GITHUB",
    )
    return result["issues"][0]


def local_plan():
    return ImplementationPlan(
        schema_version="1.0",
        operation="NEW_STRATEGY",
        target="fixture_review",
        specification_reviewed=True,
        review_note="For isolated review verification",
        max_wall_seconds=90,
        check_timeout_seconds=30,
    )


def test_compatible_review_with_authorization_binding_and_restart(setup):
    db, ledger, issue, body = setup
    registered = register(db, issue, body)
    before = db.read_bytes(), ledger.store.path.read_bytes()
    plan = local_plan()
    expected = dict(
        schema_version="1.0",
        repository="jogutierrez99/trading-lab",
        issue_number=1,
        issue_id=issue["id"],
        task_id=registered["task_id"],
        proposal_sha256=registered["proposal_sha256"],
        plan_sha256=digest(canonical(plan.model_dump(mode="json"))),
        permission="PREPARE_ONLY",
        operation=plan.operation,
        approved_by="fixture operator",
        approved_at_utc=datetime.now(UTC) - timedelta(seconds=1),
    )
    kwargs = {"ledger": ledger.store.path, "plan": plan}
    assert diagnose_issue(db, 1, **kwargs)["authorization"] == "AUTHORIZATION_REQUIRED"
    approval = ReviewAuthorization.model_validate(expected)
    with coordinator_lock(db.with_suffix(".github-intake.lock")):
        result = diagnose_issue(db, 1, approval=approval, **kwargs)
    assert result == diagnose_issue(db, 1, approval=approval, **kwargs)
    assert result["authorization"] == "BINDING_VALID"
    assert result["status"] == "COMPATIBLE_FOR_REVIEW" and not result["execution_enabled"]
    assert result["queue_state"] == ["MANUAL_REVIEW", "PREPARE_ONLY", "QUEUED"]
    assert result["work_blockers"] == []
    for change in (
        {"proposal_sha256": "a" * 64},
        {"plan_sha256": "a" * 64},
        {"issue_id": issue["id"] + 1},
        {"task_id": "another_task"},
        {"operation": "NEW_EXPERIMENT"},
    ):
        incorrect = ReviewAuthorization.model_validate(expected | change)
        assert (
            diagnose_issue(db, 1, approval=incorrect, **kwargs)["authorization"]
            == "AUTHORIZATION_BINDING_MISMATCH"
        )
    with pytest.raises(ValueError):
        ReviewAuthorization.model_validate(expected | {"permission": "RUN"})
    assert (db.read_bytes(), ledger.store.path.read_bytes()) == before


@pytest.mark.parametrize(
    ("case", "status"),
    [
        ("missing", "INSUFFICIENT_INFORMATION"),
        ("unverified", "INSUFFICIENT_INFORMATION"),
        ("runner", "REQUIRES_TECHNICAL_PROTOCOL"),
        ("portfolio", "REQUIRES_TECHNICAL_PROTOCOL"),
    ],
)
def test_technical_statuses(setup, case, status):
    db, ledger, issue, body = setup
    manifest = body["manifest"]
    if case == "missing":
        del manifest["execution_assumptions"]["sizing"]
    elif case == "unverified":
        manifest["data_requirements"]["availability"] = "UNVERIFIED"
    elif case == "runner":
        manifest["execution_assumptions"]["runner_protocol"] = "Unrecognized runner"
    elif case == "portfolio":
        manifest["data_requirements"]["assets"].append("ETH/USDT")
    register(db, issue, body)
    result = diagnose_issue(db, 1, ledger=ledger.store.path)
    assert result["status"] == status


def test_dedupe_and_tampered_checkpoint(setup):
    db, ledger, issue, body = setup
    register(db, issue, body)
    duplicate = issue | {
        "number": 2,
        "id": issue["id"] + 1,
        "html_url": issue["html_url"].removesuffix("1") + "2",
    }
    assert register(db, duplicate, body)["status"] == "DUPLICATE"
    assert diagnose_issue(db, 2)["reason"] == "DUPLICATE"
    assert diagnose_issue(db, 1, task_id="bad_task")["reason"] == "TASK_BINDING_MISMATCH"
    assert diagnose_issue(db, 1, author_id=101)["reason"] == "INVALID_GITHUB_PROVENANCE"
    with Store(db).transaction() as conn:
        conn.execute(
            "UPDATE github_intake SET proposal_json=proposal_json||' ' WHERE issue_number=1"
        )
    assert diagnose_issue(db, 1, ledger=ledger.store.path)["reason"] == "PROPOSAL_HASH_MISMATCH"


@pytest.mark.parametrize("state", ["RUNNING", "UNKNOWN"])
def test_existing_work_and_budget_block_review_readiness(setup, state):
    db, ledger, issue, body = setup
    registered = register(db, issue, body)
    ledger.reserve("fixture", "simulated uncertain call", 1)
    with Store(db).transaction() as conn:
        conn.execute(
            """INSERT INTO attempts (
                   attempt_id,task_id,number,status,repo,root,workspace,branch,base_commit,created_at_utc
               ) VALUES ('attempt_fixture', ?, 3, ?,
                         'unused','unused','unused','unused','unused','unused')
            """,
            (registered["task_id"], state),
        )
    result = diagnose_issue(db, 1, ledger=ledger.store.path)
    assert set(result["work_blockers"]) == {
        "ATTEMPT_LIMIT_REACHED",
        "ACTIVE_OR_UNCERTAIN_ATTEMPTS",
        "BUDGET_REVIEW_REQUIRED",
    }
    assert "UNKNOWN_API_SPEND" in result["budget"]["reason"]
    assert not result["execution_enabled"]


def test_review_reads_last_committed_checkpoint_with_receiver_writing(setup):
    db, ledger, issue, body = setup
    register(db, issue, body)
    kwargs = {"ledger": ledger.store.path}
    before = diagnose_issue(db, 1, **kwargs)
    with coordinator_lock(db.with_suffix(".github-intake.lock")):
        with Store(db).transaction() as writer:
            writer.execute("UPDATE github_intake SET reason='pending' WHERE issue_number=1")
            assert diagnose_issue(db, 1, **kwargs) == before
    assert diagnose_issue(db, 1, **kwargs)["admission_reason"] == "pending"


def test_interrupted_review_leaves_queue_unchanged(setup, monkeypatch):
    db, ledger, issue, body = setup
    register(db, issue, body)
    before = db.read_bytes()

    def interrupt(_manifest):
        raise KeyboardInterrupt

    with monkeypatch.context() as interrupted:
        interrupted.setattr(github_review, "check_spec_fields", interrupt)
        with pytest.raises(KeyboardInterrupt):
            diagnose_issue(db, 1, ledger=ledger.store.path)
    result = diagnose_issue(db, 1, ledger=ledger.store.path)
    assert result["queue_state"] == ["MANUAL_REVIEW", "PREPARE_ONLY", "QUEUED"]
    assert db.read_bytes() == before
