"""Bounded model-free repair, with a portable, explicitly historical pilot fixture."""

import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from process_test_support import retain_windows_processes as retain_windows_processes

from trading_lab_orchestration.contracts import HypothesisManifest, canonical
from trading_lab_orchestration.execution import Executor
from trading_lab_orchestration.execution_contracts import ExecutionPlan
from trading_lab_orchestration.execution_smoke import prepare_smoke
from trading_lab_orchestration.implementation import Coordinator
from trading_lab_orchestration.implementation_contracts import ImplementationPlan
from trading_lab_orchestration.manual_repair import SOURCE_FILES, ManualRepair
from trading_lab_orchestration.store import Store
from trading_lab_orchestration.workspaces import file_hash, git, inventory, write_json

pytestmark = pytest.mark.usefixtures("retain_windows_processes")

ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "examples/orchestration/repairs/manual_engulfing_native_index/repair.patch"


@pytest.fixture
def source(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(
        ROOT / "src/quant_lab", repo / "src/quant_lab", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copytree(ROOT / "configs", repo / "configs")
    shutil.copyfile(ROOT / "pyproject.toml", repo / "pyproject.toml")
    (repo / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/create_strategy.py", repo / "scripts/create_strategy.py")
    (repo / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n.ruff_cache/\n")
    git(repo, "init")
    git(repo, "config", "core.longpaths", "true")
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-m",
        "Historical test fixture",
    )
    store = Store(tmp_path / "coordinator.sqlite3")
    payload = json.loads((ROOT / "examples/orchestration/implementation_manual.json").read_text())
    task = store.register(HypothesisManifest.model_validate_json(canonical(payload)))["task_id"]
    coordinator = Coordinator(store)
    plan = ImplementationPlan.model_validate_json(
        (ROOT / "examples/orchestration/implementation_plan.json").read_text()
    )
    for number in (1, 2, 3):
        attempt = coordinator.prepare(task, repo, tmp_path / "a", plan, repair=number > 1)
        assert attempt["status"] == "PREPARED", attempt
        if number < 3:
            coordinator._finish(attempt["attempt_id"], "FAILED", "Historical fixture failure", True)
    workspace = Path(attempt["workspace"])
    for name, fixture in zip(
        plan.paths(), ("strategy.txt", "profile.yaml", "legacy_tests.txt"), strict=True
    ):
        (workspace / name).write_bytes(
            (ROOT / "tests/fixtures/manual_pilot_legacy" / fixture)
            .read_bytes()
            .replace(b"\r\n", b"\n")
        )
    assert {name: file_hash(workspace / name) for name in plan.paths()} == SOURCE_FILES
    request = coordinator._request(attempt)
    root = Path(attempt["root"])
    write_json(
        root / "delivery.json",
        {
            "schema_version": "1.0",
            "candidate_id": request.candidate_id,
            "task_id": task,
            "attempt_id": attempt["attempt_id"],
            "hypothesis_sha256": request.hypothesis_sha256,
            "base_commit": request.base_commit,
            "branch": request.branch,
            "status": "IMPLEMENTED",
            "summary": "Explicit historical fixture, not a new model run",
            "files": [{"path": name, "sha256": sha} for name, sha in SOURCE_FILES.items()],
            "tests_run": "NOT_RUN_BY_MODEL",
            "warnings": [],
            "blockers": [],
            "prepared_commands": [],
        },
    )
    write_json(root / "cli-probe.json", {"fixture_only": True})
    (root / "codex.jsonl").write_text("")
    (root / "codex.stderr").write_text("")
    process = {
        "exit_code": 0,
        "timed_out": False,
        "duration_seconds": 0,
        "argv": ["historical-fixture-only"],
    }
    write_json(root / "process-result.json", process)
    coordinator._native_interface = lambda *args: {"status": "NOT_CHECKED_HISTORICAL_FIXTURE"}
    assert coordinator._verify(attempt["attempt_id"], request, process)["status"] == "SUCCEEDED"
    return store, attempt, tmp_path / "r"


def apply(source):
    store, attempt, artifacts = source
    result = ManualRepair(store).apply(
        attempt["attempt_id"],
        PATCH,
        artifacts,
        "Interactive assistant fixture",
        "Operator authorizes this one technical repair",
    )
    assert result["status"] == "SUCCEEDED", result
    return result


def test_manual_repair_new_identity_and_execution(source, tmp_path):
    store, old, _ = source
    before = inventory(Path(old["workspace"]))
    with store.connection() as conn:
        original = [tuple(row) for row in conn.execute("SELECT * FROM attempts ORDER BY number")]
    row = apply(source)
    manual = ManualRepair(store)
    materialized, _, receipt_path, receipt = manual.verified(row["repair_id"])
    assert materialized["attempt_id"] != old["attempt_id"]
    assert (
        receipt["model_invocations"] == 0 and receipt["author"] == "Interactive assistant fixture"
    )
    assert receipt["source_attempt_id"] == old["attempt_id"] and "model_delivery" not in receipt
    assert receipt["native_interface"]["report"]["version"] == "1.0.1"
    assert inventory(Path(old["workspace"])) == before
    with store.connection() as conn:
        assert [
            tuple(r) for r in conn.execute("SELECT * FROM attempts ORDER BY number")
        ] == original
        assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
        wrong_parent = conn.execute("SELECT attempt_id FROM attempts WHERE number=1").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="source mismatch"):
            conn.execute(
                """INSERT INTO executions(execution_id,task_id,attempt_id,intent_sha256,
                status,root,created_at_utc,manual_repair_id)
                VALUES ('wrong_binding',?,?,?,'BLOCKED','unused_fixture_path','fixture',?)""",
                (old["task_id"], wrong_parent, "0" * 64, row["repair_id"]),
            )
    plan = ExecutionPlan.model_validate_json(
        prepare_smoke(store, row["repair_id"], tmp_path / "inputs").read_text()
    )
    executor = Executor(store)
    prepared = executor.prepare(row["repair_id"], plan, tmp_path / "executions")
    assert prepared["status"] == "PREPARED", prepared
    assert (
        prepared["attempt_id"] == old["attempt_id"]
        and prepared["manual_repair_id"] == row["repair_id"]
    )
    assert executor.validate(prepared["execution_id"])["status"] == "PREPARED"
    assert executor.run(prepared["execution_id"])["status"] == "SUCCEEDED"
    execution_request = json.loads((Path(prepared["root"]) / "request.json").read_text())
    assert execution_request["implementation_id"] == row["repair_id"]
    assert execution_request["implementation_receipt_sha256"] == file_hash(receipt_path)
    assert execution_request["source_attempt_id"] == old["attempt_id"]
    with pytest.raises(ValueError, match="already has"):
        apply(source)


def test_manual_requires_authorization_and_exact_patch(source, tmp_path):
    store, attempt, artifacts = source
    repair = ManualRepair(store)
    with pytest.raises(ValueError, match="author/authorization"):
        repair.apply(attempt["attempt_id"], PATCH, artifacts, "Fixture", "")
    bad = tmp_path / "bad.patch"
    bad.write_bytes(PATCH.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="exact reviewed"):
        repair.apply(attempt["attempt_id"], bad, artifacts, "Fixture", "Approved")
    with store.connection() as conn:
        assert conn.execute("SELECT count(*) FROM manual_repairs").fetchone()[0] == 0


def test_manual_reservation_atomic(source):
    store, attempt, artifacts = source
    with store.connection() as conn:
        conn.execute(
            "CREATE TRIGGER manual_event_failure BEFORE INSERT ON events "
            "BEGIN SELECT RAISE(ABORT,'injected'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        ManualRepair(store).apply(attempt["attempt_id"], PATCH, artifacts, "Fixture", "Approved")
    with store.connection() as conn:
        assert conn.execute("SELECT count(*) FROM manual_repairs").fetchone()[0] == 0


def test_repaired_files_cannot_be_changed(source):
    row = apply(source)
    path = Path(row["root"]) / "workspace" / next(iter(SOURCE_FILES))
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="changed after"):
        ManualRepair(source[0]).verified(row["repair_id"])


def test_unknown_repair_holds_slot_and_does_not_retry(source, monkeypatch, tmp_path):
    from trading_lab_orchestration import manual_repair

    store, attempt, artifacts = source
    repair = ManualRepair(store)

    def interrupted(*args, **kwargs):
        raise RuntimeError("Simulated interruption before patch process")

    monkeypatch.setattr(manual_repair, "run_process", interrupted)
    row = repair.apply(
        attempt["attempt_id"], PATCH, artifacts, "Fixture", "Explicit repair authorization"
    )
    assert row["status"] == "UNKNOWN"
    plan = ExecutionPlan.model_validate_json(
        prepare_smoke(store, attempt["attempt_id"], tmp_path / "inputs").read_text()
    )
    with pytest.raises(ValueError, match="active or uncertain"):
        Executor(store).prepare(attempt["attempt_id"], plan, tmp_path / "executions")
    with pytest.raises(ValueError, match="stopped confirmation"):
        repair.reconcile(row["repair_id"], False, "Inspect")
    with pytest.raises(ValueError, match="uncertain stopped"):
        repair.reconcile(row["repair_id"], True, "No identity recorded; cannot prove stopped")
    assert repair.get(row["repair_id"])["status"] == "UNKNOWN"
    with pytest.raises(ValueError, match="active or uncertain"):
        repair.apply(
            attempt["attempt_id"], PATCH, artifacts, "Fixture", "No automatic second repair"
        )
    with store.connection() as conn:
        assert conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 3
