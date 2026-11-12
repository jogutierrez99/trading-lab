"""Real Git/SQLite/subprocess integration, using a local simulated Codex executable."""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from process_test_support import retain_windows_processes as retain_windows_processes

from trading_lab_orchestration.contracts import HypothesisManifest, canonical
from trading_lab_orchestration.implementation import Coordinator, _alive
from trading_lab_orchestration.implementation_contracts import ImplementationPlan
from trading_lab_orchestration.store import APPLICATION_ID, DDL, SCHEMA_VERSION, Store
from trading_lab_orchestration.workspaces import git

pytestmark = pytest.mark.usefixtures("retain_windows_processes")

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("state", ["reused", "denied", "incomplete", "live"])
def test_reconcile_checks_birth_identity_without_relaunch(setup, monkeypatch, state):
    from trading_lab_orchestration import process_identity

    coordinator = setup[0]
    attempt = prepare(setup)
    verify = coordinator._verify
    monkeypatch.setattr(coordinator, "_verify", lambda *a: (_ for _ in ()).throw(RuntimeError()))
    result = coordinator.run(attempt["attempt_id"], setup[-1])
    assert result["status"] == "UNKNOWN" and calls(setup) == 1
    birth = json.loads(result["process_identity_json"])
    observed = dict(birth)
    if state == "reused":
        observed["created"] = str(int(birth["created"]) + 1)
    if state == "incomplete":
        with coordinator.store.transaction() as c:
            c.execute(
                "UPDATE attempts SET process_identity_json=NULL WHERE attempt_id=?",
                (attempt["attempt_id"],),
            )
    original_probe = process_identity._probe

    def probe(pid, handle=None):
        if pid == birth["pid"] and handle is None:
            if state == "denied":
                raise PermissionError("controlled denied probe")
            return observed, True
        return original_probe(pid, handle)

    monkeypatch.setattr(process_identity, "_probe", probe)
    monkeypatch.setattr(coordinator, "_verify", verify)
    if state == "reused":
        result = coordinator.reconcile(
            attempt["attempt_id"],
            "verify",
            True,
            "Review existing process result and delivery, no relaunch",
        )
        assert result["status"] == "SUCCEEDED", result
    else:
        with pytest.raises(ValueError):
            coordinator.reconcile(attempt["attempt_id"], "verify", True, "Cannot prove stopped")
        assert coordinator.attempt(attempt["attempt_id"])["status"] == "UNKNOWN"
    assert calls(setup) == 1


FAKE = r"""
import hashlib, json, os, subprocess, sys, time
from pathlib import Path
mode_path = Path(__file__).with_suffix(".mode")
mode = mode_path.read_text() if mode_path.exists() else "ok"
if mode == "registered_core" and os.environ.get("CODEX_WINDOWS_REGISTERED_CORE") == "1":
    print("desktop launcher request leaked into standalone CLI", file=sys.stderr)
    raise SystemExit(9)
if "--version" in sys.argv:
    print("codex-cli simulated-4.2")
    raise SystemExit(0)
if "--help" in sys.argv:
    print("--json --output-schema --output-last-message --sandbox --ignore-user-config --ephemeral")
    raise SystemExit(0)
if "login" in sys.argv:
    print("DO_NOT_PERSIST_AUTH_OUTPUT")
    raise SystemExit(1 if mode == "auth" else 0)
calls = Path(__file__).with_suffix(".calls")
with calls.open("a") as stream:
    stream.write("exec\n")
request = json.loads(sys.stdin.read().rsplit("\n\n", 1)[1])
if mode in ("fail", "permission", "scopefail"):
    if mode == "scopefail":
        Path("README.md").write_text("unauthorized before failure")
    print("permission denied" if mode == "permission" else "simulated failure", file=sys.stderr)
    raise SystemExit(7)
if mode == "sleep":
    descendant = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    Path(__file__).with_suffix(".childpid").write_text(str(descendant.pid))
    time.sleep(60)
target = request["plan"]["target"]
for name in ([] if mode == "blocked" else request["allowed_write_paths"]):
    path = Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    if name.startswith("src/"):
        previous = 'def previous(values):\n    return [None, *values[:-1]]\n'
        if mode == "formatfail":
            previous = 'def previous(values):\n    return [ None, *values[:-1] ]\n'
        text = ('from quant_lab.strategies.trend_following import TrendFollowing\n\n\n'
                + previous + '\n\nclass SimulatedSignal(TrendFollowing):\n'
                + f'    name = "{target}"\n')
        if mode == "nativefail":
            text += '\n    def prepare_features(self, candles):\n        return candles.timestamp\n'
    elif name.startswith("tests/"):
        text = (
            'import runpy\n\n\n'
            'def test_causal_previous():\n'
            f'    source = "src/quant_lab/strategies/{target}.py"\n'
            '    previous = runpy.run_path(source)["previous"]\n'
            '    assert previous([10, 20, 30]) == [None, 10, 20]\n'
            '    assert previous([10, 20, 30, 999])[:3] == previous([10, 20, 30])\n'
        )
        if mode == "testfail":
            text += '    assert False, "simulated implementation defect"\n'
    else:
        text = (f'name: {target}\nenabled: false\n'
                'parameters: {donchian_period: 3, ema_period: 4}\n')
    path.write_text(text, encoding="utf-8")
if mode == "scope":
    Path("README.md").write_text("unauthorized change")
delivery = {
    "schema_version": "1.0",
    "candidate_id": request["candidate_id"], "task_id": request["task_id"],
    "attempt_id": request["attempt_id"], "hypothesis_sha256": request["hypothesis_sha256"],
    "base_commit": request["base_commit"], "branch": request["branch"],
    "status": "BLOCKED" if mode == "blocked" else "IMPLEMENTED",
    "summary": "Simulated implementation, not research evidence",
    "files": [{"path": name, "sha256": hashlib.sha256(Path(name).read_bytes()).hexdigest()}
              for name in ([] if mode == "blocked" else request["allowed_write_paths"])],
    "tests_run": "NOT_RUN_BY_MODEL", "warnings": [],
    "blockers": ["Incomplete specification"] if mode == "blocked" else [],
    "prepared_commands": [],
}
if mode == "contradictory":
    delivery["candidate_id"] = "wrong_candidate"
if mode == "hash":
    delivery["files"][0]["sha256"] = "0" * 64
output = Path(sys.argv[sys.argv.index("--output-last-message") + 1])
output.write_text("invalid json" if mode == "invalid" else json.dumps(delivery), encoding="utf-8")
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 11, "output_tokens": 7}}))
"""


@pytest.mark.skipif(os.name != "nt", reason="Windows desktop launcher selection")
def test_standalone_codex_child_omits_desktop_launcher_and_keeps_sandbox(setup, monkeypatch):
    monkeypatch.setenv("CODEX_WINDOWS_REGISTERED_CORE", "1")
    coordinator = setup[0]
    attempt = prepare(setup)
    Path(setup[-1][1]).with_suffix(".mode").write_text("registered_core", encoding="utf-8")
    result = coordinator.run(attempt["attempt_id"], setup[-1])
    assert result["status"] == "SUCCEEDED", result
    argv = json.loads((Path(attempt["root"]) / "process-result.json").read_bytes())["argv"]
    assert 'windows.sandbox="elevated"' in argv
    assert 'default_permissions=":workspace"' in argv
    assert "sandbox_workspace_write.network_access=false" in argv
    assert argv[argv.index("--sandbox") + 1] == "workspace-write"
    assert argv[argv.index("-a") + 1] == "never"
    assert os.environ["CODEX_WINDOWS_REGISTERED_CORE"] == "1"


@pytest.fixture
def setup(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "core.longpaths", "true")  # Temporary fixture only.
    shutil.copytree(
        ROOT / "src/quant_lab", repo / "src/quant_lab", ignore=shutil.ignore_patterns("__pycache__")
    )
    (repo / "configs").mkdir()
    for name in ("app.yaml", "risk.yaml"):
        shutil.copyfile(ROOT / "configs" / name, repo / "configs" / name)
    (repo / "README.md").write_text("base\n")
    (repo / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n.ruff_cache/\n")
    (repo / "scripts").mkdir()
    (repo / "scripts/create_strategy.py").write_text(
        "from pathlib import Path\nimport sys\n"
        "name=sys.argv[1]\n"
        "for item in (f'src/quant_lab/strategies/{name}.py', "
        "f'configs/strategies/{name}.yaml', f'tests/unit/test_{name}.py'):\n"
        "    path=Path(item)\n    path.parent.mkdir(parents=True,exist_ok=True)\n"
        "    with path.open('x') as stream: stream.write('# exclusive scaffold\\n')\n"
    )
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-m",
        "fixture base",
    )
    (repo / "README.md").write_text("user uncommitted change\n")
    (repo / "user.txt").write_text("keep untracked\n")
    payload = json.loads((ROOT / "examples/orchestration/manual_valid.json").read_text())
    payload["requires_new_strategy_code"] = True
    payload["execution_assumptions"]["runner_protocol"] = "StudyBackend v1"
    manifest = HypothesisManifest.model_validate_json(canonical(payload))
    store = Store(tmp_path / "orchestration.sqlite3")
    task = store.register(manifest)["task_id"]
    coordinator = Coordinator(store)
    plan = ImplementationPlan(
        schema_version="1.0",
        operation="NEW_STRATEGY",
        target="simulated_signal",
        specification_reviewed=True,
        review_note="Reviewed deterministic synthetic fixture",
        # Allow Windows interpreter/pytest startup under load; this is not a latency test.
        # Production plans retain their own limits; the timeout regression overrides wall=1.
        max_wall_seconds=60,
        check_timeout_seconds=30,
    )
    fake = tmp_path / "fake_codex.py"
    fake.write_text(FAKE, encoding="utf-8")
    return coordinator, repo, tmp_path / "attempts", plan, task, [sys.executable, str(fake)]


def prepare(setup, **kwargs):
    coordinator, repo, artifacts, plan, task, _ = setup
    result = coordinator.prepare(task, repo, artifacts, plan, **kwargs)
    assert result["status"] == "PREPARED", result
    return result


def mode(setup, value):
    Path(setup[-1][-1]).with_suffix(".mode").write_text(value)


def calls(setup):
    path = Path(setup[-1][-1]).with_suffix(".calls")
    return len(path.read_text().splitlines()) if path.exists() else 0


def test_native_interface_blocks_timestamp_column_before_certifying_delivery(setup):
    mode(setup, "nativefail")
    attempt = prepare(setup)
    result = setup[0].run(attempt["attempt_id"], setup[-1])
    assert result["status"] == "FAILED", result
    assert "Native interface" in result["error"] and "timestamp" in result["error"]
    assert not list(Path(result["root"]).glob("verification_*/receipt.json"))
    native = json.loads(
        next(Path(result["root"]).glob("verification_*/native-interface.json")).read_text()
    )
    assert native["status"] == "FAILED"
    assert calls(setup) == 1  # Simulated executable only, no automatic repair.


def test_legacy_request_does_not_gain_an_undeclared_native_command(setup):
    coordinator = setup[0]
    attempt = prepare(setup)
    request = coordinator._request(attempt)
    assert request.native_interface_check == "SYNTHETIC_OHLCV_UTC_V1"
    legacy = request.model_copy(update={"native_interface_check": None})
    evidence = Path(attempt["root"]) / "undeclared-native-check"
    with pytest.raises(ValueError, match="Legacy request"):
        coordinator._native_interface(attempt, legacy, evidence, 10)
    assert not evidence.exists() and calls(setup) == 0


def test_manual_format_repair_preserves_model_evidence_and_does_not_retry(setup):
    coordinator, repo, _, _, task, command = setup
    mode(setup, "formatfail")
    attempt = prepare(setup)
    result = coordinator.run(attempt["attempt_id"], command)
    assert result["status"] == "FAILED"
    root = Path(result["root"])
    original_delivery = (root / "delivery.json").read_bytes()
    prior = next(root.glob("verification_*"))
    original_evidence = {str(p): p.read_bytes() for p in prior.rglob("*") if p.is_file()}
    original_checkout = git(repo, "status", "--porcelain")
    with pytest.raises(ValueError, match="confirmation"):
        coordinator.repair_format(attempt["attempt_id"], False, "Operator authorizes format only")
    result = coordinator.repair_format(
        attempt["attempt_id"], True, "Operator authorizes format only"
    )
    assert result["status"] == "SUCCEEDED", result
    receipt = json.loads(next(root.glob("verification_*/receipt.json")).read_text())
    repair = receipt["operator_format_repair"]
    assert repair["ast_unchanged"] is True and repair["model_invoked"] is False
    assert repair["before"] != repair["after"]
    assert receipt["files"] == repair["after"]
    assert all(item["exit_code"] == 0 for item in receipt["checks"])
    assert receipt["model_delivery"] == json.loads(original_delivery)
    assert (root / "delivery.json").read_bytes() == original_delivery
    assert all(Path(path).read_bytes() == content for path, content in original_evidence.items())
    assert coordinator.store.show(task)["task"]["status"] == "SUCCEEDED"
    assert git(repo, "status", "--porcelain") == original_checkout
    assert calls(setup) == 1
    with pytest.raises(ValueError, match="latest failed"):
        coordinator.repair_format(attempt["attempt_id"], True, "No second repair")


@pytest.mark.parametrize("failure", ["testfail", "tampering", "astchange"])
def test_manual_format_repair_rejects_non_format_changes(setup, monkeypatch, failure):
    from trading_lab_orchestration import implementation

    coordinator, _, _, plan, _, command = setup
    mode(setup, "testfail" if failure == "testfail" else "formatfail")
    attempt = prepare(setup)
    assert coordinator.run(attempt["attempt_id"], command)["status"] == "FAILED"
    source = Path(attempt["workspace"]) / plan.paths()[0]
    if failure == "tampering":
        source.write_text("def previous(values):\n    return []\n")
    original = source.read_bytes()
    if failure == "astchange":

        def bad_formatter(argv, cwd, timeout, stdout, stderr, **kwargs):
            stdout.write_text("def previous(values):\n    return []\n")
            stderr.write_text("")
            return {"exit_code": 0, "timed_out": False}

        monkeypatch.setattr(implementation, "run_process", bad_formatter)
        result = coordinator.repair_format(attempt["attempt_id"], True, "Format only")
        assert result["status"] == "FAILED"
        assert "AST" in result["error"]
    else:
        with pytest.raises((ValueError, OSError)):
            coordinator.repair_format(attempt["attempt_id"], True, "Format only")
    assert source.read_bytes() == original
    assert calls(setup) == 1
    assert not list(Path(attempt["root"]).glob("verification_*/receipt.json"))


def test_success_independent_checks_and_user_changes(setup):
    coordinator, repo, _, _, task, command = setup
    original = git(repo, "status", "--porcelain")
    attempt = prepare(setup)
    result = coordinator.run(attempt["attempt_id"], command)
    assert result["status"] == "SUCCEEDED", result
    receipts = list(Path(result["root"]).glob("verification_*/receipt.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    assert receipt["status"] == "IMPLEMENTED_VERIFIED"
    assert coordinator._request(result).native_interface_check == "SYNTHETIC_OHLCV_UTC_V1"
    assert receipt["native_interface"]["report"]["status"] == "VALID"
    assert receipt["native_interface"]["report"]["timestamp_column"] is False
    assert len(receipt["checks"]) == 3
    assert all(check["exit_code"] == 0 for check in receipt["checks"])
    assert receipt["reported_cli_usage"] == {"input_tokens": 11, "output_tokens": 7}
    assert receipt["api_cost_eur"] is None
    assert coordinator.store.show(task)["task"]["status"] == "SUCCEEDED"
    assert git(repo, "status", "--porcelain") == original
    assert (repo / "README.md").read_text() == "user uncommitted change\n"
    assert (repo / "user.txt").read_text() == "keep untracked\n"
    with pytest.raises(ValueError, match="relaunched"):
        coordinator.run(attempt["attempt_id"], command)
    assert calls(setup) == 1
    assert "DO_NOT_PERSIST_AUTH_OUTPUT" not in (Path(result["root"]) / "cli-probe.json").read_text()


@pytest.mark.parametrize(
    "failure", ["invalid", "contradictory", "hash", "testfail", "fail", "scope"]
)
def test_invalid_receipts_process_failure_and_scope(setup, failure):
    mode(setup, failure)
    attempt = prepare(setup)
    result = setup[0].run(attempt["attempt_id"], setup[-1])
    assert result["status"] == ("BLOCKED" if failure == "scope" else "FAILED"), result
    assert bool(result["retry_allowed"]) == (failure != "scope")
    assert not list(Path(result["root"]).glob("verification_*/receipt.json"))
    assert calls(setup) == 1
    assert (setup[1] / "README.md").read_text() == "user uncommitted change\n"


def test_timeout_kills_process_tree(setup):
    mode(setup, "sleep")
    coordinator, repo, artifacts, plan, task, command = setup
    plan = plan.model_copy(update={"max_wall_seconds": 1})
    attempt = coordinator.prepare(task, repo, artifacts, plan)
    result = coordinator.run(attempt["attempt_id"], command)
    assert result["status"] == "TIMED_OUT", result
    assert not _alive(result["child_pid"], result.get("process_identity_json"))
    descendant = int(Path(command[-1]).with_suffix(".childpid").read_text())
    assert not _alive(descendant)
    assert result["retry_allowed"]


@pytest.mark.parametrize("failure", ["blocked", "permission", "scopefail"])
def test_nonrepairable_blockers_and_scope_on_process_error(setup, failure):
    mode(setup, failure)
    attempt = prepare(setup)
    result = setup[0].run(attempt["attempt_id"], setup[-1])
    assert result["status"] == "BLOCKED", result
    assert not result["retry_allowed"]
    with pytest.raises(ValueError, match="repairable"):
        prepare(setup, repair=True)


def test_explicit_reconciliation_preserves_blocked_delivery_and_attempt_budget(setup):
    mode(setup, "blocked")
    coordinator = setup[0]
    first = prepare(setup)
    blocked = coordinator.run(first["attempt_id"], setup[-1])
    assert blocked["status"] == "BLOCKED" and not blocked["retry_allowed"]
    delivery = Path(first["root"]) / "delivery.json"
    original = delivery.read_bytes()
    reconciled = coordinator.reconcile(
        first["attempt_id"], "failed", True, "Stopped launch reviewed before technical retry"
    )
    assert reconciled["status"] == "FAILED" and reconciled["retry_allowed"]
    second = prepare(setup, repair=True)
    assert second["task_id"] == first["task_id"] and second["number"] == 2
    assert delivery.read_bytes() == original and calls(setup) == 1


def test_spec_gate_and_new_manual_example(setup):
    from trading_lab_orchestration.contracts import load_manifest
    from trading_lab_orchestration.implementation import review_spec

    plan = ImplementationPlan.model_validate_json(
        (ROOT / "examples/orchestration/implementation_plan.json").read_text()
    )
    manifest = load_manifest(ROOT / "examples/orchestration/implementation_manual.json")
    review_spec(manifest, plan)
    incomplete = manifest.model_copy(
        update={
            "execution_assumptions": manifest.execution_assumptions.model_copy(
                update={"stop": "PENDIENTE"}
            )
        }
    )
    with pytest.raises(ValueError, match="placeholders"):
        review_spec(incomplete, plan)
    assert setup[0].store.show(setup[4])["attempts"] == []


def test_real_process_reservation_race(setup):
    coordinator, repo, artifacts, plan, task, _ = setup
    plan_path = repo.parent / "plan.json"
    plan_path.write_text(canonical(plan.model_dump(mode="json")))
    child = """
import json, sys
from pathlib import Path
from trading_lab_orchestration.implementation import Coordinator, load_plan
from trading_lab_orchestration.store import Store
coordinator = Coordinator(Store(Path(sys.argv[1])))
print("READY", flush=True)
sys.stdin.readline()
try:
    result = coordinator.prepare(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]),
                                 load_plan(Path(sys.argv[5])))
    print(json.dumps({"status": result["status"]}), flush=True)
except ValueError:
    print(json.dumps({"status": "BUSY"}), flush=True)
"""
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    processes = []
    try:
        for _ in range(2):
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-u",
                        "-c",
                        child,
                        str(coordinator.store.path),
                        task,
                        str(repo),
                        str(artifacts),
                        str(plan_path),
                    ],
                    env=env,
                    text=True,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            )
        for process in processes:
            assert process.stdout.readline().strip() == "READY"
        for process in processes:
            process.stdin.write("GO\n")
            process.stdin.flush()
        statuses = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=25)
            assert process.returncode == 0 and not stderr, stdout + stderr
            statuses.append(json.loads(stdout)["status"])
        assert sorted(statuses) == ["BUSY", "PREPARED"]
        assert len(coordinator.store.show(task)["attempts"]) == 1
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)


@pytest.mark.parametrize("failure", ["auth", "missing"])
def test_preflight_recoverable_without_model_launch(setup, failure):
    coordinator = setup[0]
    attempt = prepare(setup)
    mode(setup, "auth" if failure == "auth" else "ok")
    executable = setup[-1] if failure == "auth" else "definitely-missing-codex-fixture"
    blocked = coordinator.run(attempt["attempt_id"], executable)
    assert blocked["status"] == "BLOCKED" and blocked["child_pid"] is None
    assert not blocked["retry_allowed"] and calls(setup) == 0
    mode(setup, "ok")
    recovered = coordinator.run(attempt["attempt_id"], setup[-1])
    assert recovered["status"] == "SUCCEEDED", recovered
    assert recovered["number"] == 1 and calls(setup) == 1


def test_concurrent_task_reservation_and_global_limit(setup):
    barrier = Barrier(2)
    coordinator, repo, artifacts, plan, task, _ = setup

    def reserve(_):
        barrier.wait(timeout=10)
        try:
            return coordinator.prepare(task, repo, artifacts, plan)["status"]
        except ValueError:
            return "BUSY"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve, range(2))) == ["BUSY", "PREPARED"]
    payload = json.loads((ROOT / "examples/orchestration/manual_valid.json").read_text())
    payload["requires_new_strategy_code"] = True
    payload["execution_assumptions"]["runner_protocol"] = "StudyBackend v1"
    payload["hypothesis_id"] = "second_candidate"
    payload["market_hypothesis"] = "different specification"
    task2 = coordinator.store.register(HypothesisManifest.model_validate_json(canonical(payload)))[
        "task_id"
    ]
    with pytest.raises(ValueError, match="active or uncertain"):
        coordinator.prepare(task2, repo, artifacts, plan)
    with coordinator.store.connection() as conn:
        assert conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 1


def test_interruption_reconcile_without_second_model_launch(setup, monkeypatch):
    coordinator = setup[0]
    attempt = prepare(setup)
    original_verify = coordinator._verify

    def interrupted(*args):
        raise RuntimeError("simulated interruption after CLI completion")

    monkeypatch.setattr(coordinator, "_verify", interrupted)
    result = coordinator.run(attempt["attempt_id"], setup[-1])
    assert result["status"] == "UNKNOWN"
    assert result["ended_at_utc"] is None
    assert calls(setup) == 1
    with pytest.raises(ValueError, match="relaunched"):
        coordinator.run(attempt["attempt_id"], setup[-1])
    monkeypatch.setattr(coordinator, "_verify", original_verify)
    with pytest.raises(ValueError, match="confirmation"):
        coordinator.reconcile(attempt["attempt_id"], "verify", False, "inspect")
    result = coordinator.reconcile(attempt["attempt_id"], "verify", True, "confirmed stopped")
    assert result["status"] == "SUCCEEDED", result
    assert calls(setup) == 1


def test_repair_limit_frozen_plan_and_prior_artifacts(setup):
    mode(setup, "fail")
    coordinator = setup[0]
    roots = []
    for number in range(1, 4):
        attempt = prepare(setup, repair=number > 1)
        roots.append(Path(attempt["root"]))
        result = coordinator.run(attempt["attempt_id"], setup[-1])
        assert result["status"] == "FAILED"
        assert result["number"] == number
    with pytest.raises(ValueError, match="Maximum three"):
        prepare(setup, repair=True)
    assert calls(setup) == 3
    assert len({root.name for root in roots}) == 3
    assert all((root / "process-result.json").exists() for root in roots)
    assert all((root / "workspace").is_dir() for root in roots)


def test_plan_and_control_tampering_blocked(setup):
    coordinator, repo, artifacts, plan, task, _ = setup
    mode(setup, "fail")
    attempt = prepare(setup)
    coordinator.run(attempt["attempt_id"], setup[-1])
    different = plan.model_copy(update={"target": "changed_hypothesis"})
    with pytest.raises(ValueError, match="cannot change"):
        coordinator.prepare(task, repo, artifacts, different, repair=True)
    attempt = prepare(setup, repair=True)
    (Path(attempt["root"]) / "prompt.txt").write_text("overridden permissions")
    blocked = coordinator.run(attempt["attempt_id"], setup[-1])
    assert blocked["status"] == "BLOCKED"
    assert calls(setup) == 1


def test_scaffold_is_sealed_and_does_not_require_model_python(setup):
    from trading_lab_orchestration.codex_adapter import CodexCLI

    attempt = prepare(setup)
    root = Path(attempt["root"])
    seeded = json.loads((root / "prepared-files.json").read_text())
    assert set(seeded) == set(setup[3].paths())
    assert json.loads((root / "scaffold-result.json").read_text())["exit_code"] == 0
    prompt = (root / "prompt.txt").read_text()
    assert "do not rerun the exclusive generator" in prompt
    assert "WindowsPowerShell" in prompt and "login=false" in prompt
    cli = CodexCLI(setup[-1])
    argv = cli.argv(Path(attempt["workspace"]), root / "schema", root / "delivery")
    assert 'default_permissions=":workspace"' in argv
    if os.name == "nt":
        assert 'windows.sandbox="elevated"' in argv
        mxc = CodexCLI(setup[-1], windows_sandbox="mxc").argv(
            Path(attempt["workspace"]), root / "schema", root / "delivery"
        )
        assert mxc == [
            'windows.sandbox="mxc"' if item == 'windows.sandbox="elevated"' else item
            for item in argv
        ]
    else:
        assert not any(value.startswith("windows.sandbox=") for value in argv)
    assert argv[argv.index("--sandbox") + 1] == "workspace-write"
    assert argv[argv.index("-a") + 1] == "never"
    assert "--add-dir" not in argv and "--ignore-rules" not in argv
    assert calls(setup) == 0
    # Changes after preparation are still rejected, even on an authorized seeded file.
    path = Path(attempt["workspace"]) / setup[3].paths()[0]
    path.write_text("unreviewed change")
    result = setup[0].run(attempt["attempt_id"], setup[-1])
    assert result["status"] == "BLOCKED" and calls(setup) == 0


def test_seed_hash_control_tampering_is_rejected(setup):
    attempt = prepare(setup)
    root = Path(attempt["root"])
    (root / "prepared-files.json").write_text("{}")
    result = setup[0].run(attempt["attempt_id"], setup[-1])
    assert result["status"] == "BLOCKED" and calls(setup) == 0


def test_v1_migration_preserves_snapshot_and_history(tmp_path):
    path = tmp_path / "v1.sqlite3"
    with sqlite3.connect(path) as conn:
        for sql in DDL:
            conn.execute(sql)
        conn.execute(f"PRAGMA application_id={APPLICATION_ID}")
        conn.execute("PRAGMA user_version=1")
        conn.execute(
            "INSERT INTO candidates VALUES ('c','h','f','{}','hash','BLOCKED','now','now')"
        )
        conn.execute(
            "INSERT INTO tasks VALUES ('t','c','key','MANUAL_REVIEW','PREPARE_ONLY',"
            "'BLOCKED','now','now')"
        )
        conn.execute(
            "INSERT INTO events VALUES (1,'c','t','task',NULL,'BLOCKED','human',"
            "'fixture','now','{}','hash')"
        )
        before = {
            table: conn.execute(f"SELECT * FROM {table}").fetchall()
            for table in ("candidates", "tasks", "events")
        }
    Store(path)
    with sqlite3.connect(path) as conn:
        for table, rows in before.items():
            assert conn.execute(f"SELECT * FROM {table}").fetchall() == rows
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_cli_process_and_queries_with_simulated_executable(setup, monkeypatch, capsys):
    from trading_lab_orchestration import cli, implementation
    from trading_lab_orchestration.codex_adapter import CodexCLI

    coordinator, repo, artifacts, plan, task, command = setup
    plan_path = repo.parent / "cli-plan.json"
    plan_path.write_text(canonical(plan.model_dump(mode="json")))
    monkeypatch.setattr(implementation, "CodexCLI", lambda executable: CodexCLI(command))
    prefix = ["--db", str(coordinator.store.path)]
    assert (
        cli.main(
            [
                *prefix,
                "process",
                task,
                "--repo",
                str(repo),
                "--artifacts",
                str(artifacts),
                "--plan",
                str(plan_path),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "SUCCEEDED"
    assert cli.main([*prefix, "attempt", result["attempt_id"]]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "SUCCEEDED"
    assert cli.main([*prefix, "show", task]) == 0
    assert json.loads(capsys.readouterr().out)["task"]["status"] == "SUCCEEDED"
    assert calls(setup) == 1


def test_secret_environment_and_unknown_usage(tmp_path, monkeypatch):
    from trading_lab_orchestration.codex_adapter import usage
    from trading_lab_orchestration.processes import safe_environment

    monkeypatch.setenv("OKX_PASSPHRASE", "fixture-not-a-real-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-not-a-real-key")
    clean = safe_environment(tmp_path)
    assert "OKX_PASSPHRASE" not in clean and "OPENAI_API_KEY" not in clean
    assert clean["PYTHONPATH"] == str(tmp_path / "src")
    output = tmp_path / "events.jsonl"
    output.write_text('[]\n{"type":"turn.completed"}\n')
    assert usage(output) is None


def test_abrupt_coordinator_exit_does_not_relaunch(setup):
    coordinator = setup[0]
    mode(setup, "sleep")
    attempt = prepare(setup)
    code = """
import sys
from pathlib import Path
from trading_lab_orchestration.store import Store
from trading_lab_orchestration.implementation import Coordinator
Coordinator(Store(Path(sys.argv[1]))).run(sys.argv[2], [sys.executable, sys.argv[3]])
"""
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    worker = subprocess.Popen(
        [
            sys.executable,
            "-c",
            code,
            str(coordinator.store.path),
            attempt["attempt_id"],
            setup[-1][-1],
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    pinned = []
    try:
        marker = Path(setup[-1][-1]).with_suffix(".childpid")
        deadline = time.monotonic() + 15
        while not marker.exists() and worker.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists()
        from trading_lab_orchestration.process_identity import capture, identity_state

        descendant_birth = capture(int(marker.read_text()))
        if os.name != "nt":
            birth = json.loads(coordinator.attempt(attempt["attempt_id"])["process_identity_json"])
            for original in (birth, descendant_birth):
                fd = os.pidfd_open(original["pid"])
                pinned.append(fd)
                assert identity_state(original["pid"], original) == "RUNNING"
        worker.kill()
        worker.communicate(timeout=10)
        assert coordinator.inspect(attempt["attempt_id"])["status"] == "UNKNOWN"
        with pytest.raises(ValueError, match="relaunched"):
            coordinator.run(attempt["attempt_id"], setup[-1])
        if os.name == "nt":
            deadline = time.monotonic() + 5
            while _alive(int(marker.read_text()), descendant_birth) and time.monotonic() < deadline:
                time.sleep(0.02)
            assert not _alive(int(marker.read_text()), descendant_birth)
            result = coordinator.reconcile(attempt["attempt_id"], "failed", True, "job stopped")
            assert result["status"] == "FAILED"
        else:
            # POSIX groups survive parent SIGKILL. Only target retained pidfds of
            # our two identified fixture children, never a reopened group number.
            import signal

            for fd in pinned:
                try:
                    signal.pidfd_send_signal(fd, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        assert calls(setup) == 1
    finally:
        for fd in pinned:
            os.close(fd)
        if worker.poll() is None:
            worker.kill()
        worker.communicate(timeout=10)
