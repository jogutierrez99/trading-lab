import csv
import io
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from trading_lab_catalog.cli import main
from trading_lab_catalog.comparison import compare
from trading_lab_catalog.ingestion import preview
from trading_lab_catalog.models import (
    Artifact,
    Bundle,
    Case,
    Decision,
    Experiment,
    Run,
    Strategy,
    Version,
)
from trading_lab_catalog.service import discover, joined_cases
from trading_lab_catalog.store import Conflict, IntegrityError, Store
from trading_lab_catalog.verification import BlockedSource, sha


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "catalog" / "strategy-catalog.sqlite3")
    store.init()
    return store


@pytest.fixture
def bundle(tmp_path):
    strategy = Strategy(
        id="fixture", name="fixture", description="Synthetic fixture", source="test"
    )
    version = Version(
        id="v1",
        strategy_id="fixture",
        semantic_version="1.0.0",
        implementation_reference="fixture",
        code_sha256="1" * 64,
    )
    experiment = Experiment(
        id="e1",
        version_id="v1",
        hypothesis="fixture",
        market_type="spot",
        asset="HYPE",
        timeframe="4h",
        direction="LONG_ONLY",
        parameters={"window": 10},
        configuration_sha256="2" * 64,
        dataset_sha256="3" * 64,
        experimental_protocol="fixture v1",
        risk={"risk_pct": 0.5},
        execution_assumptions={"timing": "NEXT_OPEN"},
        holdout="CONSUMED",
        capital_policy="RESET_PER_SEGMENT",
    )
    run = Run(
        id="r1",
        experiment_id="e1",
        engine="fixture",
        engine_version="1",
        job_sha256="4" * 64,
        status="COMPLETE",
        kind="SYNTHETIC",
        evidence_reference=str(tmp_path / "source.json"),
        evidence_sha256="5" * 64,
        audit_status="UNVERIFIED",
    )
    case = Case(
        id="c1",
        run_id="r1",
        segment="train",
        scenario="base",
        period_start_utc=datetime(2022, 1, 1, tzinfo=UTC),
        period_end_utc=datetime(2022, 2, 1, tzinfo=UTC),
        warmup_bars=240,
        trades=0,
        net_return_pct=0,
        max_drawdown_pct=0,
        capital_initial=10000,
        costs={"fee_pct": 0.1},
        audit_status="UNVERIFIED",
    )
    decision = Decision(
        id="d1",
        strategy_id="fixture",
        version_id="v1",
        run_id="r1",
        category="ECONOMIC",
        verdict="NO_DECISION",
        reasoning="No evidence",
        limitations=["Consumed holdout"],
        decided_by="fixture",
        decided_at_utc=None,
    )
    return Bundle(
        strategies=[strategy],
        versions=[version],
        experiments=[experiment],
        runs=[run],
        case_results=[case],
        research_decisions=[decision],
    )


def test_init_schema_migrations_and_queries(store, bundle):
    store.init()
    assert store.migrate() == 1
    with pytest.raises(IntegrityError):
        store.migrate(2)
    assert store.ingest(bundle, "test")["status"] == "INGESTED"
    assert store.ingest(bundle, "test")["status"] == "DUPLICATE"
    assert len(store.records("versions")) == 1
    row = joined_cases(store, asset="HYPE")[0]
    assert row["profit_factor"] is None and row["verdict"] == "NO_DECISION"
    assert row["research_state"] == "UNKNOWN"
    assert store.verify()["status"] == "OK"


def test_conflict_rolls_back_and_events_are_immutable(store, bundle):
    store.ingest(bundle, "original")
    changed = bundle.model_copy(
        update={"strategies": [bundle.strategies[0].model_copy(update={"description": "changed"})]}
    )
    with pytest.raises(Conflict):
        store.ingest(changed, "conflict")
    assert store.records("strategies")[0]["description"] == "Synthetic fixture"
    with store.connection() as c:
        kinds = [r[0] for r in c.execute("select kind from catalog_events order by event_id")]
        assert kinds[-2:] == ["INGESTED", "CONFLICT"]
        assert "REGISTERED_VERSIONS" in kinds
    with (
        pytest.raises(sqlite3.IntegrityError, match="immutable"),
        store.connection(write=True) as c,
    ):
        c.execute("DELETE FROM catalog_events")
    with (
        pytest.raises(sqlite3.IntegrityError, match="immutable"),
        store.connection(write=True) as c,
    ):
        c.execute("UPDATE runs SET payload='{}'")


def test_concurrent_duplicate_and_restart(store, bundle):
    with ThreadPoolExecutor(2) as pool:
        result = list(pool.map(lambda _: store.ingest(bundle, "concurrent"), range(2)))
    assert sorted(r["status"] for r in result) == ["DUPLICATE", "INGESTED"]
    assert len(Store(store.path).records("runs")) == 1


def test_interrupted_ingestion_atomic(store, bundle, monkeypatch):
    def interrupt(*_):
        raise KeyboardInterrupt

    monkeypatch.setattr(Store, "_event", interrupt)
    with pytest.raises(KeyboardInterrupt):
        store.ingest(bundle, "interrupted")
    assert store.records("strategies") == []


def test_versions_decisions_and_foreign_keys(store, bundle):
    store.ingest(bundle, "first")
    v2 = bundle.versions[0].model_copy(update={"id": "v2", "semantic_version": "2.0.0"})
    store.ingest(Bundle(versions=[v2]), "second")
    assert len(store.records("versions")) == 2
    with pytest.raises(Conflict):
        store.ingest(
            Bundle(
                runs=[
                    bundle.runs[0].model_copy(update={"id": "orphan", "experiment_id": "missing"})
                ]
            ),
            "orphan",
        )
    assert len(store.records("runs")) == 1


def test_discovery_adapter_uses_registry_without_creating_strategies(store):
    bundle = discover()
    assert any(s.id == "btc_spot_sma50_sma200_1h_pilot_v1" for s in bundle.strategies)
    store.ingest(bundle, "trusted discovery")
    assert store.ingest(discover(), "trusted discovery")["status"] == "DUPLICATE"
    assert not store.records("runs")


def test_decision_revision_preserves_economic_verdict(store, bundle):
    store.ingest(bundle, "fixture")
    reviewed = bundle.research_decisions[0].model_copy(
        update={
            "id": "d2",
            "category": "RESEARCH",
            "verdict": "REJECTED",
            "decided_at_utc": datetime(2026, 1, 1, tzinfo=UTC),
        }
    )
    store.ingest(Bundle(research_decisions=[reviewed]), "operator review")
    row = joined_cases(store)[0]
    assert row["verdict"] == "NO_DECISION" and row["research_state"] == "REJECTED"
    assert len(store.records("research_decisions")) == 2


def test_identical_experiment_with_another_id_is_a_conflict(store, bundle):
    store.ingest(bundle, "fixture")
    copied = bundle.experiments[0].model_copy(update={"id": "another-id"})
    with pytest.raises(Conflict):
        store.ingest(Bundle(experiments=[copied]), "same definition")
    assert len(store.records("experiments")) == 1


def test_comparable_results_do_not_choose_a_winner(store, bundle):
    store.ingest(bundle, "fixture")
    row = {
        **joined_cases(store)[0],
        "holdout": "UNOBSERVED",
        "trades": 40,
        "audit_status": "SOURCE_AUDITED",
        "run_audit_status": "SOURCE_AUDITED",
        "case_audit_status": "SOURCE_AUDITED",
        "declared_run_audit_status": "SOURCE_AUDITED",
        "declared_case_audit_status": "SOURCE_AUDITED",
    }
    comparison = compare([row, {**row, "net_return_pct": 10}])
    assert comparison["status"] == "COMPARABLE" and comparison["winner"] is None


@pytest.mark.parametrize(
    "field",
    [
        "scenario",
        "capital_policy",
        "capital_initial",
        "dataset_sha256",
        "engine",
        "period_start_utc",
        "risk",
        "execution_assumptions",
    ],
)
def test_comparison_blocks_divergence(store, bundle, field):
    store.ingest(bundle, "fixture")
    row = joined_cases(store)[0]
    other = {**row, field: "different"}
    assert compare([row, other])["status"] == "NOT_COMPARABLE"
    assert compare([row, row])["status"] == "COMPARABLE_WITH_LIMITATIONS"


def test_contract_rejects_nonfinite_and_invalid_utc(bundle):
    with pytest.raises(ValueError):
        Bundle.model_validate_json(
            bundle.model_dump_json().replace('"net_return_pct":0.0', '"net_return_pct":NaN')
        )
    with pytest.raises(ValueError):
        bundle.case_results[0].model_copy(
            update={"period_end_utc": datetime(2021, 1, 1, tzinfo=UTC)}
        ).__class__.model_validate(
            {
                **bundle.case_results[0].model_dump(),
                "period_end_utc": datetime(2021, 1, 1, tzinfo=UTC),
            }
        )


def test_foreign_database_and_shared_directory_untouched(tmp_path):
    root = tmp_path / "foreign"
    root.mkdir()
    db = root / "strategy-catalog.sqlite3"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE protected(id)")
    c.close()
    before = db.read_bytes()
    with pytest.raises(IntegrityError):
        Store(db).init()
    assert db.read_bytes() == before
    (root / "private-evidence.json").write_text("{}")
    with pytest.raises(ValueError, match="dedicated"):
        Store(db).init()
    assert db.read_bytes() == before


def test_cli_process_and_readonly(store, bundle, tmp_path, capsys):
    source = tmp_path / "bundle.json"
    source.write_text(bundle.model_dump_json())
    assert main(["--db", str(store.path), "register", str(source)]) == 0
    capsys.readouterr()
    before = store.path.read_bytes()
    result = subprocess.run(
        [sys.executable, "scripts/strategy_catalog.py", "--db", str(store.path), "stats"],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
    )
    assert result.returncode == 0 and json.loads(result.stdout)["runs"] == 1
    assert main(["--db", str(store.path), "show", "--id", "missing"]) == 3
    assert store.path.read_bytes() == before


def test_verify_sources_detects_changed_reference(store, bundle, tmp_path, capsys):
    store.ingest(bundle, "fixture")
    path = tmp_path / "artifact.json"
    path.write_bytes(b"{}")
    artifact = Artifact(
        id="a1",
        run_id="r1",
        artifact_type="fixture",
        reference=str(path),
        sha256=sha(path.read_bytes()),
        verification_status="HASH_VERIFIED",
    )
    store.ingest(Bundle(artifacts=[artifact]), "fixture")
    assert main(["--db", str(store.path), "verify", "--sources", "--record-event"]) == 0
    capsys.readouterr()
    path.write_bytes(b"altered")
    assert main(["--db", str(store.path), "verify", "--sources"]) == 5
    assert len(store.records("artifacts")) == 1


@pytest.fixture
def exported(tmp_path):
    # Declarative artificial records. No engine, dataset or runner is executed.
    from trading_lab_orchestration.historical_pilot_contract import (
        CANDLES,
        MANIFEST_SHA,
        Job,
        encode_transport,
        frozen_plan,
        plan_sha,
    )
    from trading_lab_orchestration.isolated_study_contract import CaseResult, Metrics

    root = Path(__file__).resolve().parents[2]
    plan = frozen_plan(root)
    job = Job(
        mode="HISTORICAL",
        plan=plan,
        candles_sha256="a" * 64,
        manifest_sha256=MANIFEST_SHA,
        supervisor_sha256="b" * 64,
        closure={
            CANDLES: "a" * 64,
            "src/quant_lab/study_backend.py": plan.engine_sha256,
        },
    )
    metrics = Metrics(
        closed_trades=0,
        return_pct=0,
        max_drawdown_pct=0,
        expectancy=None,
        profit_factor=None,
        win_rate_pct=None,
        average_close_exposure_pct=0,
        fees_paid=0,
        realized_net_pnl=0,
        slippage_cost_closed_trades=0,
        spread_cost_closed_trades=0,
        rejected_entries=0,
    )
    members = [
        CaseResult(
            id=c.id,
            segment=c.segment,
            scenario=c.scenario,
            costs=c.costs,
            metrics=metrics,
            trades=[],
            rejections=[],
            open_position=None,
            equity=[10000.0] * (c.bars + 1),
            exposure=[0.0] * (c.bars + 1),
        )
        for c in plan.cases
    ]
    wire = encode_transport(job, [m.model_dump(mode="json") for m in members])
    audit = {
        "economic_decision": "NO_DECISION",
        "metrics": {m.id: m.metrics.model_dump(mode="json") for m in members},
    }
    sealed = {
        "job": job.model_dump(mode="json"),
        "job_sha256": plan_sha(job),
        "status": "COMPLETE",
        "stdout": __import__("base64").b64encode(wire).decode(),
        "stdout_sha256": sha(wire),
        "audit": audit,
    }
    seal = tmp_path / "sealed.json"
    seal.write_text(json.dumps(sealed))
    source = tmp_path / "export"
    source.mkdir()
    rows = [
        dict(
            case=c.id,
            segment=c.segment,
            scenario=c.scenario,
            start=c.start.isoformat(),
            end_exclusive=c.end.isoformat(),
            warmup=c.warmup,
            **m.metrics.model_dump(mode="json"),
        )
        for c, m in zip(plan.cases, members, strict=True)
    ]
    summary = dict(
        job_sha256=plan_sha(job),
        host_receipt_sha256=sha(seal.read_bytes()),
        audit=audit,
        registry_state="SEALED",
        strategy=plan.strategy,
        image=plan.image,
        holdout=plan.holdout,
        cases=rows,
        commit="0" * 40,
    )
    (source / "summary.json").write_text(json.dumps(summary))
    (source / "source-hashes.json").write_text(
        json.dumps({"result_sha256": sha(seal.read_bytes()), "transport_sha256": sha(wire)})
    )
    (source / "informe.md").write_text("Artificial fixture")
    csv_file = io.StringIO()
    writer = csv.DictWriter(csv_file, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    (source / "metrics.csv").write_text(csv_file.getvalue())
    (source / "trades.csv").write_text("case,trade_number\n")
    for member in members:
        (source / (member.id + ".json")).write_text(member.model_dump_json())
    manifest = {p.name: sha(p.read_bytes()) for p in source.iterdir()}
    (source / "manifest.json").write_text(json.dumps(manifest))
    return source, seal, sha(seal.read_bytes())


def test_preview_confirmed_idempotency_and_no_source_effects(exported, store):
    source, seal, anchor = exported
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    bundle = preview(source, seal, anchor)
    assert len(bundle.case_results) == 6 and bundle.experiments[0].holdout == "CONSUMED"
    assert bundle.research_decisions[0].verdict == "NO_DECISION"
    assert (
        store.ingest(bundle, str(source), sealed_source=seal, receipt_sha256=anchor)["status"]
        == "INGESTED"
    )
    assert (
        store.ingest(
            preview(source, seal, anchor), str(source), sealed_source=seal, receipt_sha256=anchor
        )["status"]
        == "DUPLICATE"
    )
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before


@pytest.mark.parametrize("mutation", ["hash", "missing", "nan", "duplicate", "receipt", "resealed"])
def test_preview_rejects_corruption(exported, mutation):
    source, seal, anchor = exported
    path = source / "train_base.json"
    if mutation == "hash":
        path.write_text("{}")
    elif mutation == "missing":
        path.unlink()
    elif mutation == "receipt":
        anchor = "0" * 64
    else:
        if mutation == "nan":
            path.write_text('{"net_return_pct":NaN}')
        elif mutation == "duplicate":
            path.write_text('{"id":1,"id":2}')
        else:
            data = json.loads(path.read_bytes())
            data["metrics"]["return_pct"] = -50
            path.write_text(json.dumps(data))
        manifest = json.loads((source / "manifest.json").read_bytes())
        manifest[path.name] = sha(path.read_bytes())
        (source / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(BlockedSource):
        preview(source, seal, anchor)


@pytest.mark.parametrize("entity", ["runs", "case_results"])
def test_generic_persistence_rejects_audit_claims(store, bundle, entity):
    changed = bundle.model_copy(
        update={
            entity: [
                getattr(bundle, entity)[0].model_copy(update={"audit_status": "SOURCE_AUDITED"})
            ]
        }
    )
    with pytest.raises(IntegrityError, match="cannot accredit"):
        store.ingest(changed, "operator declaration")
    assert store.records("runs") == [] and store.records("case_results") == []


def test_generic_register_cannot_bypass_persistence(store, bundle, tmp_path, capsys):
    changed = bundle.model_copy(
        update={"runs": [bundle.runs[0].model_copy(update={"audit_status": "SOURCE_AUDITED"})]}
    )
    source = tmp_path / "declaration.json"
    source.write_text(changed.model_dump_json())
    assert main(["--db", str(store.path), "register", str(source)]) == 6
    assert "cannot accredit" in capsys.readouterr().out
    assert store.records("runs") == []


def test_artifact_integrity_requires_matching_bytes(store, bundle, tmp_path):
    store.ingest(bundle, "fixture")
    file = tmp_path / "artifact.json"
    file.write_bytes(b"{}")
    claimed = Artifact(
        id="forged",
        run_id="r1",
        artifact_type="fixture",
        reference=str(file),
        sha256="0" * 64,
        verification_status="HASH_VERIFIED",
    )
    with pytest.raises(IntegrityError, match="captured source"):
        store.ingest(Bundle(artifacts=[claimed]), "manual claim")
    assert store.records("artifacts") == []
    valid = claimed.model_copy(update={"sha256": sha(file.read_bytes())})
    store.ingest(Bundle(artifacts=[valid]), "verified file")
    assert store.records("artifacts")[0]["verification_status"] == "HASH_VERIFIED"
    assert store.records("runs")[0]["audit_status"] == "UNVERIFIED"


def test_sealed_persistence_requires_source_and_exact_bundle(exported, store, capsys):
    source, sealed, anchor = exported
    bundle = preview(source, sealed, anchor)
    with pytest.raises(IntegrityError, match="cannot accredit"):
        store.ingest(bundle, "copied preview")
    changed = bundle.model_copy(
        update={
            "case_results": [
                bundle.case_results[0].model_copy(update={"net_return_pct": 50}),
                *bundle.case_results[1:],
            ]
        }
    )
    with pytest.raises(IntegrityError, match="differs"):
        store.ingest(changed, source, sealed_source=sealed, receipt_sha256=anchor)
    store.ingest(bundle, source, sealed_source=sealed, receipt_sha256=anchor)
    assert store.records("runs")[0]["audit_status"] == "SOURCE_AUDITED"
    assert all(c["audit_status"] == "SOURCE_AUDITED" for c in store.records("case_results"))
    row = joined_cases(store)[0]
    assert row["run_audit_status"] == row["case_audit_status"] == "SOURCE_AUDITED"
    assert row["verdict"] == "NO_DECISION" and row["holdout"] == "CONSUMED"
    assert (
        main(
            [
                "--db",
                str(store.path),
                "import-confirmed",
                "--source",
                str(source),
                "--sealed-source",
                str(sealed),
                "--receipt-sha256",
                anchor,
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "DUPLICATE"


def test_manual_verification_event_is_not_audit_accreditation(store, bundle):
    store.ingest(bundle, "fixture")
    store.record_verification({"status": "SOURCE_AUDITED", "run_id": "r1"})
    assert store.records("runs")[0]["audit_status"] == "UNVERIFIED"
    row = joined_cases(store)[0]
    forged_case_claim = {**row, "audit_status": "SOURCE_AUDITED"}
    result = compare([forged_case_claim, forged_case_claim])
    assert result["status"] == "COMPARABLE_WITH_LIMITATIONS"
    assert "Evidence is not source-audited" in result["reasons"]


def test_legacy_unbacked_claims_are_not_accreditations(store, bundle):
    store.ingest(bundle, "fixture")
    # Model an old schema-1 database containing manually asserted audit flags.
    # No original database is used. Only this disposable fixture loses its triggers.
    from trading_lab_catalog.models import canonical, fingerprint

    with store.connection(write=True) as c:
        c.execute("DROP TRIGGER case_results_no_update")
        legacy = bundle.case_results[0].model_copy(update={"audit_status": "SOURCE_AUDITED"})
        data = legacy.model_dump(mode="json")
        c.execute(
            "UPDATE case_results SET payload=?,sha256=? WHERE id=?",
            (canonical(data), fingerprint(data), legacy.id),
        )
    assert store.records("case_results")[0]["audit_status"] == "UNVERIFIED"
    row = joined_cases(store)[0]
    result = compare([row, row])
    assert result["status"] == "COMPARABLE_WITH_LIMITATIONS"
    assert "Run and case audit provenance disagree" in result["reasons"]


@pytest.fixture
def discovery_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    strategy = root / "src/quant_lab/strategies/fixture.py"
    config = root / "configs/strategies/fixture.yaml"
    strategy.parent.mkdir(parents=True)
    config.parent.mkdir(parents=True)
    strategy.write_text("# trusted test source\n")
    config.write_text("enabled: false\n")

    def git(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

    git("init")
    git("config", "user.name", "Catalogue fixture")
    git("config", "user.email", "catalogue@example.invalid")
    git("add", "--", "src", "configs")
    git("commit", "-m", "test fixture")
    checked = subprocess.run(
        ["git", "-C", str(root), "cat-file", "blob", "HEAD:src/quant_lab/strategies/fixture.py"],
        capture_output=True,
    )
    assert checked.returncode == 0, checked.stderr
    cls = SimpleNamespace(parameter_model=SimpleNamespace(model_json_schema=lambda: {}))
    row = {
        "strategy_id": "fixture",
        "version": "1.0.0",
        "description": "fixture",
        "implementation": "fixture.Strategy",
        "config": "configs/strategies/fixture.yaml",
        "status": "experimental",
        "created_at": None,
        "timeframes": ["1h"],
        "modes": ["LONG_ONLY"],
    }
    registry = SimpleNamespace(catalogue=lambda: [row], implementation=lambda _: cls)
    return root, strategy, config, registry


@pytest.mark.parametrize("target", ["strategy", "config"])
def test_discovery_rejects_modified_relevant_files(discovery_repo, monkeypatch, target):
    root, strategy, config, registry = discovery_repo
    monkeypatch.setattr("trading_lab_catalog.service.inspect.getfile", lambda _: str(strategy))
    initial = discover(registry, root=root)
    assert initial.versions[0].git_commit is not None
    assert discover(registry, root=root) == initial
    (strategy if target == "strategy" else config).write_text("# uncommitted change\n")
    with pytest.raises(ValueError, match="clean strategy"):
        discover(registry, root=root)


def test_discovery_rejects_untracked_strategy(discovery_repo):
    root, strategy, _, registry = discovery_repo
    (strategy.parent / "untracked.py").write_text("# uncommitted\n")
    with pytest.raises(ValueError, match="clean strategy"):
        discover(registry, root=root)
