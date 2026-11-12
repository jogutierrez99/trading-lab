"""4.6 fake Codex, real Git/SQLite/native six-case synthetic runner, no services."""

import json
import os
import shutil
import sys
from pathlib import Path

import pytest
from process_test_support import retain_windows_processes as retain_windows_processes

from trading_lab_orchestration.circuit import CircuitRunner, circuit_doctor
from trading_lab_orchestration.circuit_contracts import CircuitRequest
from trading_lab_orchestration.contracts import load_manifest
from trading_lab_orchestration.store import Store
from trading_lab_orchestration.workspaces import file_hash, git

pytestmark = pytest.mark.usefixtures("retain_windows_processes")

ROOT = Path(__file__).resolve().parents[2]
FAKE = r"""
import hashlib,json,sys
from pathlib import Path
if '--version' in sys.argv:
 print('codex-cli SIMULATED circuit46');raise SystemExit(0)
if '--help' in sys.argv:
 print('--json --output-schema --output-last-message --sandbox '
       '--ignore-user-config --ephemeral');raise SystemExit(0)
if 'login' in sys.argv:raise SystemExit(0)
p=Path(__file__);mode=p.with_suffix('.mode').read_text()
with p.with_suffix('.calls').open('a') as f:f.write('simulated\n')
r=json.loads(sys.stdin.read().rsplit('\n\n',1)[1]);number=r['attempt_number']
if mode=='permission':
 print('permission denied',file=sys.stderr);raise SystemExit(7)
for name in r['allowed_write_paths']:
 path=Path(name)
 if name.startswith('src/'):
  text=p.with_suffix('.template').read_text()
  if mode=='native':text=text.replace('frame = candles.copy()','frame = candles.timestamp')
 elif name.startswith('configs/'):
  text='name: '+r['plan']['target']+'\nversion: 1.0.0\nenabled: false\nparameters: {}\n'
 else:
  text=p.with_suffix('.test').read_text()
  if mode=='native':text='def test_placeholder_for_native_guard():\n    assert True\n'
  if mode=='exhaust' or (mode=='repair' and number==1):
   text+='\n\ndef test_deliberate_technical_failure():\n    assert False\n'
 path.write_text(text,encoding='utf-8')
delivery={'schema_version':'1.0','candidate_id':r['candidate_id'],'task_id':r['task_id'],
 'attempt_id':r['attempt_id'],'hypothesis_sha256':r['hypothesis_sha256'],'base_commit':r['base_commit'],
 'branch':r['branch'],'status':'IMPLEMENTED',
 'summary':'SIMULATED implementation, not an AI integration',
 'files':[{'path':n,'sha256':hashlib.sha256(Path(n).read_bytes()).hexdigest()}
          for n in r['allowed_write_paths']],
 'tests_run':'NOT_RUN_BY_MODEL','warnings':['SIMULATED CODEX'],'blockers':[],'prepared_commands':[]}
output=Path(sys.argv[sys.argv.index('--output-last-message')+1])
output.write_text(json.dumps(delivery),encoding='utf-8')
"""

NATIVE_TEST = """import numpy as np
import pandas as pd

from quant_lab.config import StrategyConfig
from quant_lab.strategies.integration_candle_pulse_v1 import IntegrationCandlePulseV1


def test_native_causal_contract():
    strategy = IntegrationCandlePulseV1(StrategyConfig(name="integration_candle_pulse_v1"))
    close = np.full(50, 100.0)
    close[25] = 100.25
    close[27] = 99.75
    frame = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": close, "volume": 10.0},
        index=pd.date_range("2000-01-01", periods=50, freq="h", tz="UTC"),
    )
    before = frame.copy()
    signals = strategy.generate_signals(frame)
    assert signals.long_entries[25] and signals.long_exits[27]
    assert not any(signals.long_entries[:20])
    assert not any(signals.short_entries) and not any(signals.short_exits)
    assert strategy.generate_signals(frame.iloc[:30]).long_entries == signals.long_entries[:30]
    pd.testing.assert_frame_equal(frame, before)
"""


@pytest.fixture
def setup(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    shutil.copytree(
        ROOT / "src/quant_lab", repo / "src/quant_lab", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copytree(ROOT / "configs", repo / "configs")
    (repo / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/create_strategy.py", repo / "scripts/create_strategy.py")
    shutil.copyfile(ROOT / "pyproject.toml", repo / "pyproject.toml")
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
        "fixture",
    )
    fake = tmp_path / "fake.py"
    fake.write_text(FAKE)
    fake.with_suffix(".mode").write_text("ok")
    shutil.copyfile(
        ROOT / "tests/fixtures/circuit_pulse_strategy.txt", fake.with_suffix(".template")
    )
    fake.with_suffix(".test").write_text(NATIVE_TEST)
    request = CircuitRequest.model_validate_json(
        (ROOT / "examples/orchestration/circuit46.json").read_text()
    )
    store = Store(tmp_path / "state/coordinator.sqlite3")
    driver = CircuitRunner(store, simulated=True)
    monkeypatch.setattr(
        "socket.create_connection",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("No services")),
    )
    return driver, request, repo, tmp_path / "circuits", [sys.executable, str(fake)], fake


def launch(setup, resume=False):
    d, r, repo, out, exe, _ = setup
    return d.start(r, repo, out, exe, resume=resume)


def test_flow1_pauses_for_billing_and_resumes_only_auditor_and_draft(
    setup, tmp_path, monkeypatch, capsys
):
    import subprocess
    from datetime import UTC, date, datetime
    from types import SimpleNamespace

    from trading_lab_orchestration import audit_model, audit_openai, billing, billing_snapshots
    from trading_lab_orchestration.audit_model import Budget
    from trading_lab_orchestration.cli import main
    from trading_lab_orchestration.flow1 import draft, research_request
    from trading_lab_orchestration.research_intake import REDUCED_MODEL, ingest, load_batch

    driver, _, repo, artifacts, executable, _ = setup
    billing_time = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)

    class SnapshotClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return billing_time.astimezone(tz)

    monkeypatch.setattr(billing_snapshots, "datetime", SnapshotClock)
    monkeypatch.setattr(audit_model, "utc_now", billing_time.isoformat)
    monkeypatch.setattr(audit_openai, "PRICE_REVIEWED", date.min)
    monkeypatch.setattr(audit_openai, "PRICE_EXPIRES", date.max)
    budget = Budget(Store(tmp_path / "ledger/api.sqlite3"))
    budget.open_month(0, "Simulated spend")
    calls = []

    def answer(model, content):
        calls.append(model)
        return {
            "model": model,
            "service_tier": "default",
            "status": "completed",
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 100,
                "input_tokens_details": {"cached_tokens": 0},
            },
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": json.dumps(content)},
                    ],
                }
            ],
        }

    def research(_):
        return answer(
            REDUCED_MODEL,
            {
                "idea_id": "flow1_candle_pulse_v1",
                "title": "Synthetic flow",
                "rationale": "Acceptance only",
                "limitations": [],
                "missing": [],
            },
        )

    def audit(packet):
        return answer(
            audit_openai.DEFAULT_MODEL,
            {
                "schema_version": "1.0",
                "findings": ["Synthetic evidence only"],
                "uncertainties": [],
                "verdict": "NO_DECISION",
                "demo_authorized": False,
                "evidence_references": [next(iter(packet["references"]))],
            },
        )

    scope = ("org-fixture", "proj_fixture")
    published = []
    reads = []

    def admin_get(endpoint, query, _, organization):
        assert organization == scope[0] and query["project_ids"] == [scope[1]]
        start = query["start_time"]
        reads.append(endpoint)
        if endpoint == "usage/completions":
            rows = [
                dict(
                    project_id=scope[1],
                    model=model,
                    service_tier="default",
                    num_model_requests=1,
                    input_tokens=1000,
                    output_tokens=100,
                    input_cached_tokens=0,
                )
                for model in calls
            ]
        else:
            assert endpoint == "costs"
            rows = [
                dict(
                    organization_id=scope[0],
                    project_id=scope[1],
                    line_item=f"{model}, {direction}",
                    quantity=quantity,
                    quantity_unit="tokens",
                    amount=dict(value=price, currency="usd"),
                )
                for model in published
                for direction, quantity, price in (
                    ("input", 1000, "0.00015"),
                    ("output", 100, "0.00006"),
                )
            ]
        return json.dumps(
            {
                "has_more": False,
                "data": [
                    {"start_time": start, "end_time": start + 86400, "results": rows},
                ],
            }
        ).encode()

    monkeypatch.setenv("TRADING_LAB_GLOBAL_API_DB", str(budget.store.path))
    monkeypatch.setenv("OPENAI_ADMIN_KEY", "simulated-admin")
    monkeypatch.setattr(billing, "_get", admin_get)
    batch = load_batch(ROOT / "examples/orchestration/research_batch_flow1_sequential.json")
    research_provider = SimpleNamespace(
        name="openai", model=REDUCED_MODEL, post=research, billing_scope=scope
    )
    intake_args = (batch, budget, driver.store.path, tmp_path / "research", research_provider, 4)
    intake = ingest(*intake_args, profile="reduced")
    assert intake["queue_status"] == "QUEUED"
    request, _ = research_request(driver.store, budget, intake["dossier"])
    paused = driver.start(request, repo, artifacts, executable)
    assert paused["status"] == "AWAITING_MODEL_AUDIT", paused
    assert paused["task_id"] == intake["task_id"] and paused["notification_id"] is None
    assert paused["attempts_used"] == 1 and paused["audit_id"] and paused["execution_id"]
    execution = driver.executor.get(paused["execution_id"])
    assert execution["status"] == "SUCCEEDED"
    receipt = Path(execution["error"].removeprefix("Execution receipt: "))
    pinned = file_hash(receipt)
    review_dir = tmp_path / "model-review"
    audit_provider = SimpleNamespace(
        name="openai", model=audit_openai.DEFAULT_MODEL, call=audit, billing_scope=scope
    )
    maximum = audit_openai.quote(audit_provider.model)["maximum_cents"]
    audit_args = (driver.store, budget, paused["audit_id"], review_dir, audit_provider, maximum)

    def args_for(call_id):
        return [
            "--db",
            str(driver.store.path),
            "flow1-billing-cycle",
            call_id,
            "--budget-db",
            str(budget.store.path),
            "--project-id",
            "proj_fixture",
            "--research-dossier",
            intake["dossier"],
            "--model-dossier",
            str(review_dir),
        ]

    def cycle(call_id, capsys):
        assert main(args_for(call_id)) == 0
        return json.loads(capsys.readouterr().out)

    waiting = cycle(intake["call_id"], capsys)
    assert waiting["status"] == "WAITING_BILLING"
    assert waiting["billing"]["reason_code"] == "COST_NOT_AVAILABLE"
    assert cycle(intake["call_id"], capsys) == waiting
    with pytest.raises(ValueError, match="UNKNOWN_API_SPEND"):
        audit_openai.supplement(*audit_args)
    assert calls == [REDUCED_MODEL] and not review_dir.exists()
    resumed = driver.start(request, repo, artifacts, executable, resume=True)
    assert resumed == driver.inspect(request.circuit_id)
    assert resumed == {
        k: v for k, v in paused.items() if k not in {"outcome_receipt", "outcome_sha256"}
    }
    with driver.store.connection() as conn:
        assert conn.execute("SELECT count(*) FROM audit_outbox").fetchone()[0] == 0

    published[:] = calls
    ready = cycle(intake["call_id"], capsys)
    assert ready["status"] == "READY_FOR_AUDITOR_PREFLIGHT"
    assert ready["billing"]["status"] == "SETTLED" and len(calls) == 1
    monkeypatch.setattr(audit_openai, "load_openai_key", lambda _: "simulated-model-key")
    assert (
        main(
            [
                "--db",
                str(budget.store.path),
                "audit-openai-doctor",
                paused["audit_id"],
                "--source-db",
                str(driver.store.path),
            ]
        )
        == 0
    )
    preflight = json.loads(capsys.readouterr().out)
    assert preflight["status"] == "READY" and preflight["network_calls"] == 0
    assert preflight["pricing"]["maximum_cents"] == maximum and len(calls) == 1
    model_review = audit_openai.supplement(*audit_args)
    assert model_review["status"] == "COMPLETED"
    assert cycle(intake["call_id"], capsys)["status"] == "AUDITOR_ALREADY_RESERVED"
    with pytest.raises(ValueError, match="already exists"):
        audit_openai.supplement(*audit_args)
    assert cycle(model_review["call_id"], capsys)["status"] == "WAITING_BILLING"
    published[:] = calls
    completed = cycle(model_review["call_id"], capsys)
    assert completed["status"] == "NOTICE_PREPARED" and completed["billing"]["status"] == "SETTLED"
    final = driver.inspect(request.circuit_id)
    assert final["status"] == "NOTICE_PREPARED" and final["preview"]["status"] == "DRAFT"
    assert final["preview"]["attempts"] == 0 and final["preview"]["message_id"] is None
    assert draft(driver.store, budget, intake["dossier"], review_dir) == final
    assert ingest(*intake_args, profile="reduced") == intake
    assert driver.start(request, repo, artifacts, executable, resume=True) == final
    assert file_hash(receipt) == pinned
    assert calls == [REDUCED_MODEL, audit_openai.DEFAULT_MODEL]
    assert [r["status"] for r in budget.inspect()["calls"]] == ["SETTLED", "SETTLED"]
    assert len(reads) == 14
    env = os.environ.copy()
    env.pop("OPENAI_ADMIN_KEY", None)  # A restarted worker can replay even without credentials.
    restarted = subprocess.run(
        [
            sys.executable,
            "-B",
            str(ROOT / "scripts/orchestrator.py"),
            *args_for(model_review["call_id"]),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=True,
        timeout=30,
    )
    replay = json.loads(restarted.stdout)
    assert (
        replay["status"] == "NOTICE_PREPARED" and replay["billing"]["status"] == "ALREADY_SETTLED"
    )
    assert replay["billing"]["released_now_cents"] == 0
    assert replay["notification_id"] == completed["notification_id"] == final["notification_id"]
    with driver.store.connection() as conn:
        for table in ("tasks", "attempts", "executions", "audits", "audit_outbox"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 1


def test_satisfactory_native_circuit_no_operations_control_and_repeat(setup):
    d, r, repo, _, _, fake = setup
    # A separate earlier dossier must not change, including its consumed attempt metadata.
    previous = d.store.register(load_manifest(ROOT / "examples/orchestration/manual_valid.json"))
    with d.store.transaction() as c:
        for number in (1, 2, 3):
            c.execute(
                "INSERT INTO attempts(attempt_id,task_id,number,status,repo,root,workspace,"
                "branch,base_commit,created_at_utc) "
                "VALUES(?,?,?,'FAILED','old','old','old','old','old','old')",
                ("earlier_" + str(number), previous["task_id"], number),
            )
    before = d.store.show(previous["task_id"])
    result = launch(setup)
    assert result["status"] == "NOTICE_PREPARED", result
    assert result["success_on_initial_attempt"] and not result["success_after_repair"]
    assert result["preview"]["status"] == "DRAFT" and result["preview"]["attempts"] == 0
    assert result["simulated"] == 1 and not result["demo_authorized"]
    assert d.store.show(previous["task_id"]) == before
    with d.store.connection() as c:
        assert c.execute("SELECT count(*) FROM executions").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM audits").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM audit_outbox").fetchone()[0] == 1
    assert launch(setup)["notification_id"] == result["notification_id"]
    assert fake.with_suffix(".calls").read_text().count("simulated") == 1
    assert not (repo / "src/quant_lab/strategies/integration_candle_pulse_v1.py").exists()
    with d.store.transaction() as c:
        c.execute(
            "UPDATE audit_outbox SET status='UNKNOWN' WHERE notification_id=?",
            (result["notification_id"],),
        )
    assert launch(setup)["status"] == "UNCERTAIN"
    assert fake.with_suffix(".calls").read_text().count("simulated") == 1


@pytest.mark.parametrize(
    "mode,attempts,success",
    [("repair", 2, True), ("exhaust", 3, False), ("native", 3, False), ("permission", 1, False)],
)
def test_technical_repair_budget_and_native_block(setup, mode, attempts, success):
    *_, fake = setup
    fake.with_suffix(".mode").write_text(mode)
    result = launch(setup)
    assert result["attempts_used"] == attempts, result
    assert (result["status"] == "NOTICE_PREPARED") == success, result
    if success:
        assert result["success_after_repair"] and not result["success_on_initial_attempt"]
    else:
        assert result["status"] == "BLOCKED"
        assert not result["execution_id"] and not result["notification_id"]
    assert fake.with_suffix(".calls").read_text().count("simulated") == attempts
    for a in result["attempts"]:
        assert Path(a["root"]).exists()


def test_interrupt_after_completed_backtest_resumes_without_duplicate_execution(setup, monkeypatch):
    d, *_ = setup
    original = d.executor.run
    calls = []

    def interrupted(identifier):
        value = original(identifier)
        calls.append(value)
        assert value["status"] == "SUCCEEDED", value
        raise KeyboardInterrupt()

    monkeypatch.setattr(d.executor, "run", interrupted)
    with pytest.raises(KeyboardInterrupt):
        launch(setup)
    assert d.get(setup[1].circuit_id)["status"] == "UNCERTAIN"
    result = launch(setup, resume=True)
    assert result["status"] == "NOTICE_PREPARED", result
    assert len(calls) == 1
    with d.store.connection() as c:
        assert c.execute("SELECT count(*) FROM executions").fetchone()[0] == 1


def test_interrupted_model_intent_requires_reconciliation_no_second_launch(setup, monkeypatch):
    d, *_ = setup
    monkeypatch.setattr(d.coordinator, "run", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        launch(setup)
    assert launch(setup, resume=True)["status"] == "UNCERTAIN"
    assert not setup[-1].with_suffix(".calls").exists()


def test_offline_preflight_has_limits_without_initializing_or_launching(setup):
    d, r, repo, out, exe, fake = setup
    before = file_hash(d.store.path)
    result = circuit_doctor(d.store.path, r, repo, out, exe)
    assert result["limits"]["technical_repairs"] == 2 and result["telegram"] == "PREVIEW_ONLY"
    assert result["authentication"].startswith("NOT_CHECKED")
    assert file_hash(d.store.path) == before and not out.exists()
    assert not fake.with_suffix(".calls").exists()


def test_explicit_reconciliation_of_long_path_failure_keeps_budget_and_evidence(setup, monkeypatch):
    import json

    from trading_lab_orchestration import implementation

    d, r, *_, fake = setup
    original = implementation.create_workspace
    monkeypatch.setattr(
        implementation,
        "create_workspace",
        lambda *a: (_ for _ in ()).throw(ValueError("git checkout: Filename too long")),
    )
    blocked = launch(setup)
    assert blocked["status"] == "BLOCKED" and blocked["attempts_used"] == 1
    assert not fake.with_suffix(".calls").exists()
    hashes = json.loads(d.get(r.circuit_id)["evidence_json"])
    # --resume alone must not grant retry permission.
    assert launch(setup, resume=True)["status"] == "BLOCKED"
    d.coordinator.reconcile(
        blocked["attempt_id"],
        "failed",
        True,
        "Operator authorizes retry after long-path adapter fix; no model started",
    )
    monkeypatch.setattr(implementation, "create_workspace", original)
    result = launch(setup, resume=True)
    assert result["status"] == "NOTICE_PREPARED", result
    assert result["attempts_used"] == 2 and result["repairs_used"] == 1
    assert result["success_after_repair"] and not result["success_on_initial_attempt"]
    assert fake.with_suffix(".calls").read_text().count("simulated") == 1
    for name, sha in hashes.items():
        assert file_hash(Path(result["root"]) / name) == sha


@pytest.mark.skipif(os.name != "nt", reason="Windows acceptance profile")
def test_final_windows_acceptance_records_native_birth_and_synthetic_coverage(setup):
    driver, _, repo, out, command, fake = setup
    request = CircuitRequest.model_validate_json(
        (ROOT / "examples/orchestration/circuit46_acceptance.json").read_text()
    )
    template = fake.with_suffix(".template")
    template.write_text(
        template.read_text()
        .replace("integration_candle_pulse_v1", "integration_candle_pair_v1")
        .replace("IntegrationCandlePulseV1", "IntegrationCandlePairV1")
        .replace(
            "previous = frame.close.shift(1).le(frame.open.shift(1))",
            "bullish = frame.close.gt(frame.open)\n"
            "        previous = bullish.shift(1, fill_value=False)\n"
            "        previous &= ~bullish.shift(2, fill_value=False)\n"
            "        previous &= contiguous.shift(1, fill_value=False)",
        )
        .replace("frame.close.lt(frame.open)", "frame.close.le(frame.open)")
    )
    fake.with_suffix(".test").write_text(
        NATIVE_TEST.replace("integration_candle_pulse_v1", "integration_candle_pair_v1")
        .replace("IntegrationCandlePulseV1", "IntegrationCandlePairV1")
        .replace("close[25] = 100.25", "close[25:27] = 100.25")
        .replace("signals.long_entries[25]", "signals.long_entries[26]")
    )
    result = driver.start(request, repo, out, command)
    assert result["status"] == "NOTICE_PREPARED", result
    assert result["attempts_used"] == 1 and not result["operator_resume_used"]
    assert result["preview"]["status"] == "DRAFT" and result["preview"]["attempts"] == 0
    evidence = json.loads(result["evidence_json"])
    root = Path(result["root"])
    identities = json.loads(
        (root / next(n for n in evidence if n.startswith("process_identity_"))).read_text()
    )["result"]
    assert set(identities) == {"model", "native_probe", "runner"}
    assert all(i["clock"] == "WINDOWS_FILETIME_100NS" for i in identities.values())
    coverage = json.loads(
        (root / next(n for n in evidence if n.startswith("coverage_"))).read_text()
    )["result"]["cases"]
    assert len(coverage) == 6
    assert all(
        c["closed_trades"] > 0 if c["symbol"] == "BTCUSDT" else c["closed_trades"] == 0
        for c in coverage
    )
