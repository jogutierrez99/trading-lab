"""Native isolated lab execution and deterministic lifecycle regressions; synthetic data only."""

import json
import shutil
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
import yaml
from process_test_support import retain_windows_processes as retain_windows_processes

from trading_lab_orchestration.contracts import HypothesisManifest, canonical
from trading_lab_orchestration.execution import Executor
from trading_lab_orchestration.execution_contracts import ExecutionPlan
from trading_lab_orchestration.execution_smoke import prepare_smoke
from trading_lab_orchestration.implementation import Coordinator, _alive
from trading_lab_orchestration.implementation_contracts import ImplementationPlan
from trading_lab_orchestration.store import Store
from trading_lab_orchestration.workspaces import file_hash, git, inventory, write_json

pytestmark = pytest.mark.usefixtures("retain_windows_processes")

ROOT = Path(__file__).resolve().parents[2]


def rmm_fixture(repo, payload):
    import pandas as pd

    from quant_lab.literature_data import write_bundle
    from trading_lab_orchestration.rmm_comparison import BASELINE_EXPERIMENT, VARIANT

    index = pd.date_range("2024-01-01", periods=1040, freq="4h", tz="UTC", name="open_time")
    close = pd.Series([100 + i / 100 + i % 4 / 10 for i in range(len(index))], index=index)
    frame = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0}
    )
    baseline_path = repo / BASELINE_EXPERIMENT
    baseline = yaml.safe_load(baseline_path.read_text())
    pins, refs = [], []
    for market in baseline["markets"]:
        asset = market["symbol"]
        bundle = write_bundle(repo, asset, "4h", frame, {"kind": "synthetic_fixture"})
        market["dataset"] = "../../" + bundle.relative_to(repo).as_posix()
        market["dataset_id"] = bundle.name
        metadata = bundle / "manifest.json"
        pins.append(
            {
                "path": str(bundle),
                "dataset_id": bundle.name,
                "manifest_sha256": file_hash(metadata),
                "parquet_sha256": file_hash(bundle / "candles.parquet"),
                "kind": "SYNTHETIC",
                "provenance_note": "Deterministic fixture",
                "provenance_files": {str(metadata): file_hash(metadata)},
            }
        )
        refs.append(f"{asset} 4h | dataset_id={bundle.name} | synthetic")
    baseline_path.write_text(yaml.safe_dump(baseline), encoding="utf-8")
    payload["hypothesis_id"] = VARIANT
    payload["data_requirements"].update(
        assets=["BTCUSDT", "ETHUSDT"],
        timeframe="4h",
        warmup_bars=1000,
        dataset_refs=refs,
        funding_policy="NOT_MODELLED",
    )
    payload["execution_assumptions"].update(
        market_mode="synthetic", runner_protocol="StudyBackend v1"
    )
    for name, first, end in (
        ("train", 1000, 1012),
        ("validation", 1012, 1024),
        ("test", 1024, 1036),
    ):
        payload["evaluation_plan"][name] = {
            "start": index[first].isoformat(),
            "end": index[end].isoformat(),
        }
    return pins


@pytest.mark.parametrize("receipts", [True, False])
def test_reused_pid_reconciliation_requires_receipts_and_never_executes_again(
    setup, monkeypatch, receipts
):
    from trading_lab_orchestration import execution, process_identity

    executor = setup[0]
    row = prepared(setup)
    executor.validate(row["execution_id"])
    finalize = executor._finalize
    original_run = execution.run_process
    calls = []

    def counted(*a, **kw):
        calls.append(1)
        return original_run(*a, **kw)

    monkeypatch.setattr(execution, "run_process", counted)
    monkeypatch.setattr(executor, "_finalize", lambda *a: (_ for _ in ()).throw(RuntimeError()))
    result = executor.run(row["execution_id"])
    assert result["status"] == "UNKNOWN"
    birth = json.loads(result["process_identity_json"])
    observed = birth | {"created": str(int(birth["created"]) + 1)}
    original_probe = process_identity._probe
    monkeypatch.setattr(
        process_identity,
        "_probe",
        lambda pid, handle=None: (
            (observed, True)
            if pid == birth["pid"] and handle is None
            else original_probe(pid, handle)
        ),
    )
    if not receipts:
        (Path(row["root"]) / "process-result.json").unlink()
    monkeypatch.setattr(executor, "_finalize", finalize)
    result = executor.reconcile(
        row["execution_id"], "verify", True, "Controlled PID reuse; inspect existing evidence only"
    )
    assert result["status"] == ("SUCCEEDED" if receipts else "UNKNOWN"), result
    assert len(calls) == 1
    with executor.store.connection() as c:
        assert c.execute("SELECT count(*) FROM executions").fetchone()[0] == 1


@pytest.fixture
def setup(tmp_path, request):
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(
        ROOT / "src/quant_lab", repo / "src/quant_lab", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copytree(ROOT / "configs", repo / "configs")
    shutil.copyfile(ROOT / "pyproject.toml", repo / "pyproject.toml")
    (repo / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/create_strategy.py", repo / "scripts/create_strategy.py")
    (repo / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n.ruff_cache/\ndata/\n")
    payload = json.loads((ROOT / "examples/orchestration/implementation_manual.json").read_text())
    option = getattr(request, "param", None)
    rmm = option in {"rmm", "rmm_divergent"}
    if rmm:
        from trading_lab_orchestration.rmm_comparison import VARIANT

        pins = rmm_fixture(repo, payload)
    git(repo, "init")
    git(repo, "config", "core.longpaths", "true")  # Only this temporary fixture repository.
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-m",
        "Synthetic fixture only",
    )
    store = Store(tmp_path / "coordinator.sqlite3")
    task = store.register(HypothesisManifest.model_validate_json(canonical(payload)))["task_id"]
    coordinator = Coordinator(store)
    plan = ImplementationPlan(
        schema_version="1.0",
        operation="NEW_STRATEGY",
        target=VARIANT if rmm else "coordinated_fixture",
        specification_reviewed=True,
        review_note="Synthetic infrastructure fixture",
        max_wall_seconds=120,
        check_timeout_seconds=30,
    )
    attempt = coordinator.prepare(task, repo, tmp_path / "implementations", plan)
    assert attempt["status"] == "PREPARED", attempt
    workspace = Path(attempt["workspace"])
    (workspace / plan.paths()[0]).write_text(
        "from quant_lab.strategies.trend_following import TrendFollowing\n\n\n"
        'class CoordinatedFixture(TrendFollowing):\n    name = "coordinated_fixture"\n'
    )
    with_format_repair = option is True
    legacy_index_contract = option == "index_contract"
    if legacy_index_contract:
        source = workspace / plan.paths()[0]
        with source.open("a") as handle:
            handle.write(
                "\n    def prepare_features(self, candles):\n        return candles.timestamp\n"
            )
    if with_format_repair:
        source = workspace / plan.paths()[0]
        source.write_text(
            source.read_text().replace(
                'name = "coordinated_fixture"', 'name = ("coordinated_fixture")'
            )
        )
    (workspace / plan.paths()[1]).write_text(
        yaml.safe_dump(
            {
                "name": plan.target,
                "enabled": False,
                "parameters": {"donchian_period": 3, "ema_period": 4},
            }
        )
    )
    if rmm:
        from trading_lab_orchestration.rmm_comparison import BASELINE_PROFILE

        (workspace / plan.paths()[0]).write_text(
            "from quant_lab.strategies.risk_managed_momentum_v1 import "
            "RiskManagedMomentumV1Strategy\n"
            "\n\nclass SyntheticRmmVariant(RiskManagedMomentumV1Strategy):\n"
            f'    name = "{VARIANT}"\n'
            "\n    def _entries(self, features, side):\n"
            "        return super()._entries(features, side) & (side > 0)\n"
        )
        profile = yaml.safe_load((workspace / BASELINE_PROFILE).read_text())
        profile.update(name=VARIANT, enabled=False)
        if option == "rmm_divergent":
            profile["risk"]["max_position_pct"] = 24.0
        (workspace / plan.paths()[1]).write_text(yaml.safe_dump(profile))
    (workspace / plan.paths()[2]).write_text("def test_fixture_only():\n    assert 1 + 1 == 2\n")
    root = Path(attempt["root"])
    request = coordinator._request(attempt)
    delivery = {
        "schema_version": "1.0",
        "candidate_id": request.candidate_id,
        "task_id": task,
        "attempt_id": attempt["attempt_id"],
        "hypothesis_sha256": request.hypothesis_sha256,
        "base_commit": request.base_commit,
        "branch": request.branch,
        "status": "IMPLEMENTED",
        "summary": "Test-only delivery fixture; no model invoked",
        "files": [{"path": name, "sha256": file_hash(workspace / name)} for name in plan.paths()],
        "tests_run": "NOT_RUN_BY_MODEL",
        "warnings": [],
        "blockers": [],
        "prepared_commands": [],
    }
    write_json(root / "delivery.json", delivery)
    write_json(root / "cli-probe.json", {"test_fixture": True})
    (root / "codex.jsonl").write_text("")
    (root / "codex.stderr").write_text("")
    process = {
        "exit_code": 0,
        "timed_out": False,
        "duration_seconds": 0,
        "argv": ["test-fixture-only"],
    }
    write_json(root / "process-result.json", process)
    native_gate = coordinator._native_interface
    if legacy_index_contract:
        # Explicit historical fixture: old receipts predate the new implementation gate.
        coordinator._native_interface = lambda *args: {"status": "NOT_CHECKED_LEGACY_FIXTURE"}
    result = coordinator._verify(attempt["attempt_id"], request, process)
    coordinator._native_interface = native_gate
    if with_format_repair:
        assert result["status"] == "FAILED"
        result = coordinator.repair_format(attempt["attempt_id"], True, "Fixture format repair")
    assert result["status"] == "SUCCEEDED", result
    if rmm:
        from trading_lab_orchestration.rmm_comparison import BASELINE_EXPERIMENT, BASELINE_FILES

        execution_plan = ExecutionPlan.model_validate_json(
            canonical(
                {
                    "schema_version": "1.0",
                    "experiment": str(repo / BASELINE_EXPERIMENT),
                    "experiment_sha256": file_hash(repo / BASELINE_EXPERIMENT),
                    "protocol": "StudyBackend v1 / lab_experiment_v1",
                    "scope": "RMM_TRAIN_VALIDATION",
                    "all_declared_periods_authorized": False,
                    "review_note": "Synthetic scoped comparison",
                    "enable_execution_copy": True,
                    "datasets": pins,
                    "max_wall_seconds": 90,
                    "validation_timeout_seconds": 60,
                    "max_backtests": 24,
                    "max_candles": 3000,
                    "max_dataset_bytes": 1000000,
                    "comparison": {
                        "task_id": request.task_id,
                        "candidate_id": request.candidate_id,
                        "hypothesis_sha256": request.hypothesis_sha256,
                        "baseline_commit": request.base_commit,
                        "periods": ["train", "validation"],
                        "baseline_files": {
                            name: file_hash(workspace / name) for name in BASELINE_FILES
                        },
                    },
                }
            )
        )
    else:
        plan_file = prepare_smoke(store, attempt["attempt_id"], tmp_path / "smoke-inputs")
        execution_plan = ExecutionPlan.model_validate_json(plan_file.read_text())
    return Executor(store), attempt, execution_plan, tmp_path / "executions"


def prepared(setup):
    executor, attempt, plan, output = setup
    row = executor.prepare(attempt["attempt_id"], plan, output)
    assert row["status"] == "PREPARED", row
    return row


@pytest.mark.parametrize("setup", ["rmm"], indirect=True)
def test_rmm_comparison_24_cases_without_test_and_no_crossed_receipts(setup):
    from trading_lab_orchestration.rmm_comparison import paired_metrics

    executor, attempt, plan, output = setup
    wrong = plan.model_copy(
        update={"comparison": plan.comparison.model_copy(update={"candidate_id": "cand_other"})}
    )
    blocked = executor.prepare(attempt["attempt_id"], wrong, output)
    assert blocked["status"] == "BLOCKED"
    assert "variant evidence mismatch" in blocked["error"]
    row = prepared(setup)
    root = Path(row["root"])
    scope = executor.validate(row["execution_id"])
    assert scope["report"]["total_backtests"] == 24, scope
    assert scope["report"]["periods"] == ["train", "validation"]
    request = executor._load(row)
    assert all(
        info["manifest"]["source"]["window_end_exclusive"] == "2024-06-19T16:00:00+00:00"
        for info in scope["report"]["datasets"]
    )
    assert all(
        Path(info["path"]).is_relative_to(Path(request.workspace))
        for info in scope["report"]["datasets"]
    )
    result = executor.run(row["execution_id"])
    assert result["status"] == "SUCCEEDED", result
    report = json.loads((root / "comparison.json").read_text())
    assert report["backtests"] == 24
    assert {cell["period"] for cell in report["paired_metrics"]} == {"train", "validation"}
    assert len(report["paired_metrics"]) == 12
    baseline = root / report["branches"]["baseline"]["run_directory"]
    variant = root / report["branches"]["variant"]["run_directory"]
    assert baseline != variant
    with pytest.raises(ValueError, match="wrong identity"):
        paired_metrics(variant, baseline)
    receipt = json.loads(next(root.glob("verification_*/receipt.json")).read_text())
    assert receipt["artifacts_sha256"]["comparison.json"] == file_hash(root / "comparison.json")


@pytest.mark.parametrize("setup", ["rmm_divergent"], indirect=True)
def test_rmm_comparison_blocks_a_different_risk_profile(setup):
    executor, *_ = setup
    row = prepared(setup)
    result = executor.validate(row["execution_id"])
    assert result["status"] == "BLOCKED"
    assert "divergent configuration" in result["error"]
    assert not (Path(row["root"]) / "results").exists()


def test_native_run_isolated_receipt_and_no_duplicate(setup):
    executor, attempt, _, _ = setup
    before = inventory(Path(attempt["workspace"]))
    row = prepared(setup)
    identifier = row["execution_id"]
    assert executor.validate(identifier)["validation"] == "FULL"
    assert executor.validate(identifier)["already_validated"]
    result = executor.run(identifier)
    assert result["status"] == "SUCCEEDED", result
    receipt_path = next(Path(row["root"]).glob("verification_*/receipt.json"))
    receipt = json.loads(receipt_path.read_text())
    assert receipt["runner_outcome"] == {"status": "COMPLETE", "backtests": 3}
    assert receipt["run_id"] and receipt["economic_assessment"] == "NOT_ASSESSED"
    assert receipt["demo_authorized"] is False
    assert "codex" not in receipt["command"]
    assert all(
        file_hash(Path(row["root"]) / name) == sha
        for name, sha in receipt["artifacts_sha256"].items()
    )
    assert inventory(Path(attempt["workspace"])) == before
    assert not _alive(result["child_pid"], result.get("process_identity_json"))
    with pytest.raises(ValueError, match="relaunched"):
        executor.run(identifier)
    with pytest.raises(ValueError, match="Duplicate"):
        prepared(setup)
    assert executor.store.show(attempt["task_id"])["status"] == "IMPLEMENTATION_READY"


def test_concurrent_reservation_and_blocks_model_preparation(setup):
    executor, attempt, plan, output = setup
    barrier = Barrier(2)

    def reserve():
        barrier.wait(timeout=10)
        try:
            return executor.prepare(attempt["attempt_id"], plan, output)["status"]
        except ValueError:
            return "BUSY"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result() for f in [pool.submit(reserve), pool.submit(reserve)]]
    assert sorted(results) == ["BUSY", "PREPARED"]
    with executor.store.connection() as conn:
        assert conn.execute("SELECT count(*) FROM executions").fetchone()[0] == 1
    payload = json.loads((ROOT / "examples/orchestration/implementation_manual.json").read_text())
    payload["hypothesis_id"] = "second_implementation"
    payload["market_hypothesis"] = "Different test-only hypothesis"
    task = executor.store.register(HypothesisManifest.model_validate_json(canonical(payload)))[
        "task_id"
    ]
    other = ImplementationPlan(
        schema_version="1.0",
        operation="NEW_STRATEGY",
        target="other_fixture",
        specification_reviewed=True,
        review_note="Fixture",
        max_wall_seconds=30,
        check_timeout_seconds=15,
    )
    with pytest.raises(ValueError, match="heavy execution"):
        Coordinator(executor.store).prepare(task, Path(attempt["repo"]), output / "other", other)


@pytest.mark.parametrize("change", ["implementation", "execution", "dataset", "receipt", "request"])
def test_changes_after_verification_blocked(setup, change):
    executor, attempt, plan, _ = setup
    row = prepared(setup)
    source = Path(attempt["workspace"]) / "src/quant_lab/strategies/coordinated_fixture.py"
    files = {
        "implementation": source,
        "execution": Path(row["root"])
        / "workspace/src/quant_lab/strategies/coordinated_fixture.py",
        "dataset": Path(plan.datasets[0].path) / "candles.parquet",
        "receipt": Path(attempt["root"]) / "delivery.json",
        "request": Path(row["root"]) / "request.json",
    }
    files[change].write_bytes(files[change].read_bytes() + b"\n")
    assert executor.validate(row["execution_id"])["status"] == "BLOCKED"
    assert not (Path(row["root"]) / "runner.stdout").exists()


@pytest.mark.parametrize("problem", ["missing", "disabled", "bytes", "candles", "backtests"])
def test_missing_data_and_volume_limits(setup, problem):
    executor, attempt, plan, output = setup
    if problem == "missing":
        (Path(plan.datasets[0].path) / "candles.parquet").unlink()
    updates = {
        "disabled": {"enable_execution_copy": False},
        "bytes": {"max_dataset_bytes": 1},
        "candles": {"max_candles": 1},
        "backtests": {"max_backtests": 1},
    }
    plan = plan.model_copy(update=updates.get(problem, {}))
    row = executor.prepare(attempt["attempt_id"], plan, output)
    if row["status"] == "PREPARED":
        row = executor.validate(row["execution_id"])
    assert row["status"] == "BLOCKED", row
    assert not (Path(row["root"]) / "results").exists()


def test_interruption_reconcile_does_not_rerun(setup, monkeypatch):
    executor = setup[0]
    row = prepared(setup)
    executor.validate(row["execution_id"])
    finalize = executor._finalize
    monkeypatch.setattr(
        executor, "_finalize", lambda _: (_ for _ in ()).throw(RuntimeError("interrupted"))
    )
    assert executor.run(row["execution_id"])["status"] == "UNKNOWN"
    with pytest.raises(ValueError, match="active or uncertain"):
        prepared(setup)
    with pytest.raises(ValueError, match="confirmation"):
        executor.reconcile(row["execution_id"], "verify", False, "Stopped")
    monkeypatch.setattr(executor, "_finalize", finalize)
    assert (
        executor.reconcile(
            row["execution_id"], "verify", True, "Stopped; inspect existing artifacts"
        )["status"]
        == "SUCCEEDED"
    )
    assert len(list((Path(row["root"]) / "results").glob("*/*/run.json"))) == 1


def test_timeout_process_tree_and_explicit_retry(setup, monkeypatch):
    executor, attempt, plan, output = setup
    plan = plan.model_copy(update={"max_wall_seconds": 1})
    row = executor.prepare(attempt["attempt_id"], plan, output)
    assert executor.validate(row["execution_id"])["status"] == "PREPARED"
    original = executor._command
    descendant_file = Path(row["root"]) / "test-descendant.pid"

    def sleeping(request, action, result):
        return [
            sys.executable,
            "-c",
            "import subprocess,sys,time; from pathlib import Path; "
            "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); "
            "Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(60)",
            str(descendant_file),
        ]

    monkeypatch.setattr(executor, "_command", sleeping)
    result = executor.run(row["execution_id"])
    assert result["status"] == "TIMED_OUT", result
    assert not _alive(result["child_pid"], result.get("process_identity_json"))
    assert descendant_file.is_file() and not _alive(int(descendant_file.read_text()))
    monkeypatch.setattr(executor, "_command", original)
    with pytest.raises(ValueError, match="Duplicate"):
        executor.prepare(attempt["attempt_id"], plan, output)
    retry = executor.prepare(attempt["attempt_id"], plan, output, retry_of=row["execution_id"])
    assert retry["status"] == "PREPARED" and retry["execution_id"] != row["execution_id"]


@pytest.mark.parametrize("setup", [True], indirect=True)
def test_final_identity_includes_format_repair(setup):
    executor = setup[0]
    row = prepared(setup)
    request = json.loads((Path(row["root"]) / "request.json").read_text())
    repair = request["operator_format_repair"]
    assert repair["ast_unchanged"]
    assert repair["before"] != repair["after"]
    assert request["implementation_final_files"] == repair["after"]
    assert executor.validate(row["execution_id"])["status"] == "PREPARED"


@pytest.mark.parametrize("setup", ["index_contract"], indirect=True)
def test_native_index_contract_is_checked_before_backtest(setup):
    executor = setup[0]
    row = prepared(setup)
    result = executor.validate(row["execution_id"])
    assert result["status"] == "BLOCKED"
    assert "timestamp" in result["error"] and "native indexed OHLCV" in result["error"]
    assert not (Path(row["root"]) / "results").exists()


def test_runner_failure_is_not_success(setup, monkeypatch):
    executor = setup[0]
    row = prepared(setup)
    assert executor.validate(row["execution_id"])["status"] == "PREPARED"
    monkeypatch.setattr(
        executor, "_command", lambda *args: [sys.executable, "-c", "import sys;sys.exit(7)"]
    )
    result = executor.run(row["execution_id"])
    assert result["status"] == "FAILED"
    receipt = json.loads(next(Path(row["root"]).glob("verification_*/receipt.json")).read_text())
    assert receipt["process"]["exit_code"] == 7
    assert receipt["runner_outcome"] is None and receipt["run_id"] is None


def test_reservation_rolls_back_if_event_fails(setup):
    executor, attempt, plan, output = setup
    with executor.store.connection() as conn:
        conn.execute(
            "CREATE TRIGGER injected_execution_event BEFORE INSERT ON events "
            "BEGIN SELECT RAISE(ABORT,'injected execution event'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        executor.prepare(attempt["attempt_id"], plan, output)
    with executor.store.connection() as conn:
        assert conn.execute("SELECT count(*) FROM executions").fetchone()[0] == 0
        conn.execute("DROP TRIGGER injected_execution_event")
    assert prepared(setup)["status"] == "PREPARED"


def test_prepared_execution_can_be_explicitly_cancelled(setup):
    executor = setup[0]
    row = prepared(setup)
    assert (
        executor.reconcile(row["execution_id"], "cancel", True, "Cancel reserved job")["status"]
        == "CANCELLED"
    )


def test_missing_process_evidence_stays_unknown(setup):
    executor = setup[0]
    row = prepared(setup)
    executor._state(row["execution_id"], "RUNNING", "Simulated owner disappearance")
    assert executor.inspect(row["execution_id"])["status"] == "UNKNOWN"
    for outcome in ("verify", "failed"):
        with pytest.raises(ValueError, match="stopped recorded PID"):
            executor.reconcile(
                row["execution_id"],
                outcome,
                True,
                "Operator statement cannot replace missing process identity",
            )
        assert executor.get(row["execution_id"])["status"] == "UNKNOWN"
