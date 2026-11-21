"""Synthetic catalogue builders. Never point these helpers at an existing database."""

from datetime import UTC, datetime

from trading_lab_catalog.models import (
    Artifact,
    Bundle,
    Case,
    Decision,
    Experiment,
    Run,
    Strategy,
    Version,
    canonical,
    fingerprint,
    now,
)
from trading_lab_catalog.schema import REFERENCES
from trading_lab_catalog.store import Store


def make_catalogue(root, *, audited=False, comparable=False):
    path = root / "catalog" / "strategy-catalog.sqlite3"
    assert not path.exists()
    store = Store(path)
    store.init()
    strategy = Strategy(id="s", name="Synthetic", description="Synthetic fixture", source="fixture")
    version = Version(
        id="v",
        strategy_id="s",
        semantic_version="1.0.0",
        implementation_reference="fixture.Strategy",
        code_sha256="a" * 64,
        metadata={"discovered": True, "secret": "never-return"},
    )
    exp = Experiment(
        id="e",
        version_id="v",
        hypothesis="Synthetic hypothesis",
        market_type="spot",
        asset="BTCUSDT",
        timeframe="1h",
        direction="LONG_ONLY",
        parameters={"window": 50},
        configuration_sha256="b" * 64,
        dataset_sha256="c" * 64,
        experimental_protocol="fixture",
        risk={"risk_pct": 0.5},
        execution_assumptions={"timing": "NEXT_OPEN"},
        holdout="UNOBSERVED" if comparable else "CONSUMED",
        capital_policy="RESET_PER_SEGMENT",
    )
    audit = "SOURCE_AUDITED" if audited else "UNVERIFIED"
    run = Run(
        id="r",
        experiment_id="e",
        engine="fixture",
        engine_version="1",
        job_sha256="d" * 64,
        status="COMPLETE",
        kind="SYNTHETIC",
        evidence_reference="C:/Users/private/receipt.json",
        evidence_sha256="e" * 64,
        audit_status=audit,
    )
    c = Case(
        id="c1",
        run_id="r",
        segment="train",
        scenario="base",
        period_start_utc=datetime(2022, 1, 1, tzinfo=UTC),
        period_end_utc=datetime(2022, 2, 1, tzinfo=UTC),
        warmup_bars=240,
        trades=40 if comparable else 0,
        net_return_pct=None,
        max_drawdown_pct=None,
        win_rate_pct=None,
        profit_factor=None,
        capital_initial=10000,
        costs={"fee_pct": 0.1},
        audit_status=audit,
    )
    other = c.model_copy(update={"id": "c2", "scenario": "adverse", "costs": {"fee_pct": 0.2}})
    runs = [run]
    if comparable:
        second_run = run.model_copy(update={"id": "comparison-run", "job_sha256": "f" * 64})
        runs.append(second_run)
        other = c.model_copy(update={"id": "c2", "run_id": second_run.id})
    artifact = Artifact(
        id="a",
        run_id="r",
        artifact_type="fixture",
        reference="C:/Users/private/receipt.json",
        sha256="e" * 64,
        verification_status="HASH_VERIFIED" if audited else "UNVERIFIED",
    )
    decision = Decision(
        id="d",
        strategy_id="s",
        version_id="v",
        run_id="r",
        category="ECONOMIC",
        verdict="NO_DECISION",
        reasoning="Synthetic only",
        limitations=["Small sample"],
        decided_by="fixture",
        decided_at_utc=None,
    )
    bundle = Bundle(
        strategies=[
            strategy,
            Strategy(id="empty", name="Empty", description="No runs", source="fixture"),
        ],
        versions=[version, version.model_copy(update={"id": "v2", "semantic_version": "2.0.0"})],
        experiments=[exp],
        runs=runs,
        case_results=[c, other],
        artifacts=[artifact],
        research_decisions=[decision],
    )
    if not audited:
        store.ingest(bundle, "synthetic fixture")
    else:
        # Materialize an already-accepted synthetic source. This does not test
        # sealed-source ingestion, which is covered by the original V1 suite.
        with store.connection(write=True) as conn:
            for table, refs in REFERENCES.items():
                for r in bundle.model_dump(mode="json")[table]:
                    cols = ["id", "payload", "sha256", "registered_at_utc", *refs]
                    vals = [r["id"], canonical(r), fingerprint(r), now(), *(r[k] for k in refs)]
                    conn.execute(
                        f"INSERT INTO {table}({','.join(cols)}) VALUES("
                        + ",".join("?" for _ in vals)
                        + ")",
                        vals,
                    )
                    if table in ("runs", "case_results", "artifacts"):
                        kind = (
                            "HASH_VERIFIED_artifacts"
                            if table == "artifacts"
                            else "SOURCE_AUDITED_" + table
                        )
                        Store._event(
                            conn, kind, "synthetic accepted-source fixture", fingerprint(r)
                        )
            Store._event(conn, "INGESTED", "fixture", fingerprint(bundle.model_dump(mode="json")))
    return store, bundle


def extra_experiment(bundle, key):
    return Experiment.model_validate(
        {
            **bundle.experiments[0].model_dump(mode="json"),
            "id": key,
            "parameters": {"window": int(key.removeprefix("e"))},
            "parameter_fingerprint": None,
        }
    )
