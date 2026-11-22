"""Synthetic already-audited dossiers and independent catalogue fixtures only."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from trading_lab_agents.receipts import ReceiptBook
from trading_lab_agents.validator import QuantValidator
from trading_lab_agents.validator_context import ValidatorContext
from trading_lab_agents.validator_evidence import AuditDocument, PreparedAudit
from trading_lab_agents.validator_provider import FakeValidatorProvider
from trading_lab_catalog.models import (
    Artifact,
    Bundle,
    Case,
    Decision,
    Experiment,
    Run,
    Strategy,
    Version,
    fingerprint,
    now,
)
from trading_lab_catalog.schema import REFERENCES
from trading_lab_catalog.store import Store
from trading_lab_catalog.verification import sha
from trading_lab_orchestration.audit_contracts import AuditVerdict
from trading_lab_orchestration.contracts import canonical

ROOT = Path(__file__).parents[2]


def inventory(root):
    return {
        str(p.relative_to(root)): sha(p.read_bytes()) if p.is_file() else "DIR"
        for p in root.rglob("*")
    }


def create_fixture(
    root,
    *,
    source_audited=True,
    hash_verified=True,
    trades=5,
    holdout="CONSUMED",
    capital_policy="RESET_PER_SEGMENT",
    cases=True,
    case_updates=None,
    run_updates=None,
    verdict_updates=None,
    csv_bytes=None,
    metric_updates=None,
    run_id="r",
    comparable=False,
):
    """Seed a synthetic source, not an operational ingestion or accreditation API."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / "catalogue" / "strategy-catalog.sqlite3"
    store = Store(path)
    store.init()
    audit_state = "SOURCE_AUDITED" if source_audited else "UNVERIFIED"
    strategy = Strategy(
        id="s", name="Synthetic strategy", description="Fixture only", source="fixture"
    )
    version = Version(
        id="v",
        strategy_id="s",
        semantic_version="1.0.0",
        implementation_reference="synthetic",
        code_sha256="a" * 64,
    )
    exp = Experiment(
        id="e",
        version_id="v",
        hypothesis="Synthetic prior research",
        market_type="spot",
        asset="BTCUSDT",
        timeframe="1h",
        direction="LONG_ONLY",
        parameters={"window": 20},
        configuration_sha256="b" * 64,
        dataset_sha256="c" * 64,
        experimental_protocol="synthetic_prepared_audit_v1",
        risk={"risk_per_trade_pct": 0.5},
        execution_assumptions={"entry_timing": "NEXT_OPEN"},
        holdout=holdout,
        capital_policy=capital_policy,
    )
    csv_bytes = csv_bytes or b"backtest_id,filter_status\nc1,FAIL\nc2,FAIL\n"
    receipt = canonical(
        {"run_id": run_id, "execution_status": "SUCCEEDED", "scope": "SYNTHETIC_PRIOR_RECEIPT"}
    ).encode()
    run = Run(
        id=run_id,
        experiment_id="e",
        engine="synthetic_fixture",
        engine_version="1",
        job_sha256="d" * 64,
        status="COMPLETE",
        kind="SYNTHETIC",
        evidence_reference="C:/Users/private/receipt.json",
        evidence_sha256=sha(receipt),
        audit_status=audit_state,
    )
    if run_updates:
        run = Run.model_validate({**run.model_dump(mode="json"), **run_updates})
    rows = []
    for i, scenario in enumerate(("base", "base" if comparable else "adverse")):
        payload = {
            "id": f"c{i + 1}" if run_id == "r" else f"{run_id}.c{i + 1}",
            "run_id": run_id,
            "segment": "train",
            "scenario": scenario,
            "period_start_utc": datetime(2024, 1, 1, tzinfo=UTC),
            "period_end_utc": datetime(2024, 2, 1, tzinfo=UTC),
            "warmup_bars": 240,
            "trades": trades,
            "net_return_pct": 0.5 if i == 0 else -0.8,
            "max_drawdown_pct": 1.5,
            "win_rate_pct": 40.0 if trades else None,
            "profit_factor": None,
            "capital_initial": 10000.0,
            "costs": {
                "trading_fee_pct": 0.05 if i == 0 or comparable else 0.1,
                "slippage_pct": 0.03,
                "spread_pct": 0.01,
            },
            "metrics": {"sharpe": None},
            "audit_status": audit_state,
        }
        payload.update((case_updates or {}).get(i, {}))
        rows.append(Case.model_validate(payload))
    if comparable:
        # The catalogue correctly forbids duplicate segment/scenario within one
        # run. Comparable observations therefore need separate synthetic runs.
        rows = rows[:1]
    if not cases:
        rows = []
    artifact = Artifact(
        id="a" if run_id == "r" else run_id + ".a",
        run_id=run_id,
        artifact_type="synthetic_metrics_csv",
        reference="C:/Users/private/metrics.csv",
        sha256=sha(csv_bytes),
        verification_status="HASH_VERIFIED" if hash_verified else "UNVERIFIED",
    )
    decision = Decision(
        id="d" if run_id == "r" else run_id + ".d",
        strategy_id="s",
        version_id="v",
        run_id=run_id,
        category="ECONOMIC",
        verdict="NO_DECISION",
        reasoning="Prior synthetic source",
        limitations=["No economic validation"],
        decided_by="synthetic fixture",
        decided_at_utc=None,
    )
    bundle = Bundle(
        strategies=[strategy],
        versions=[version],
        experiments=[exp],
        runs=[run],
        case_results=rows,
        artifacts=[artifact],
        research_decisions=[decision],
    )
    # This matches the accepted-source fixture convention used in catalogue/API
    # tests. It does not grant real SOURCE_AUDITED or touch a production store.
    with store.connection(write=True) as conn:
        for table, refs in REFERENCES.items():
            for record in bundle.model_dump(mode="json")[table]:
                columns = ["id", "payload", "sha256", "registered_at_utc", *refs]
                values = [
                    record["id"],
                    canonical(record),
                    fingerprint(record),
                    now(),
                    *(record[k] for k in refs),
                ]
                conn.execute(
                    f"INSERT INTO {table}({','.join(columns)}) VALUES("
                    + ",".join("?" for _ in values)
                    + ")",
                    values,
                )
                if table in ("runs", "case_results") and source_audited:
                    Store._event(
                        conn,
                        "SOURCE_AUDITED_" + table,
                        "synthetic accepted-source fixture",
                        fingerprint(record),
                    )
                if table == "artifacts" and hash_verified:
                    Store._event(
                        conn,
                        "HASH_VERIFIED_artifacts",
                        "synthetic bytes fixture",
                        fingerprint(record),
                    )
        Store._event(
            conn, "INGESTED", "synthetic fixture", fingerprint(bundle.model_dump(mode="json"))
        )
    documents = {"execution_receipt": receipt, "native:metrics.csv": csv_bytes}
    native = []
    for case in rows:
        metrics = {
            "backtest_id": case.id,
            "status": "completed",
            "closed_trades": case.trades,
            "return_pct": case.net_return_pct,
            "max_drawdown_pct": case.max_drawdown_pct,
            "win_rate_pct": case.win_rate_pct,
            "profit_factor": case.profit_factor,
            "starting_equity": case.capital_initial,
            **case.metrics,
        }
        metrics.update((metric_updates or {}).get(case.id, {}))
        result = {
            "metrics": metrics,
            "trades": [{"fixture": True} for _ in range(case.trades)],
            "rejections": [],
            "equity_sha256": "f" * 64,
        }
        native.append(
            {
                "backtest_id": case.id,
                "metadata": {
                    "symbol": exp.asset,
                    "timeframe": exp.timeframe,
                    "mode": exp.direction,
                    "period": case.segment,
                    "scenario": case.scenario,
                    "start": case.period_start_utc.isoformat(),
                    "end": case.period_end_utc.isoformat(),
                    "costs": case.costs,
                    "parameters": exp.parameters,
                },
                "result": result,
            }
        )
        documents["result:" + case.id] = canonical(result).encode()
    verdict = {
        "schema_version": "1.0",
        "audit_id": "audit_fixture" if run_id == "r" else "audit_" + run_id,
        "audit_task_id": "audit_fixture" if run_id == "r" else "audit_" + run_id,
        "task_id": "task_fixture",
        "candidate_id": "candidate_fixture",
        "implementation_id": "implementation_fixture",
        "execution_id": "execution_fixture",
        "experiment_id": "e",
        "run_id": run_id,
        "auditor_profile": "quant_auditor_v1",
        "auditor_version": "1.0",
        "effective_review_mode": "DETERMINISTIC_ONLY",
        "audit_timestamp_utc": "2026-11-22T00:00:00Z",
        "audit_status": "COMPLETED_WITH_LIMITATIONS",
        "gates": {
            k: {
                "status": status,
                "findings": ["Prior deterministic fixture observation"],
                "references": ["execution_receipt"],
            }
            for k, status in (
                ("A", "INTEGRITY_OK"),
                ("B", "DESIGN_LIMITED"),
                ("C", "INSUFFICIENT_EVIDENCE"),
                ("D", "NOT_READY"),
            )
        },
        "auditor_verdict": "NO_DECISION",
        "original_classifications": [
            {"source": "native:metrics.csv", "rows": [{"filter_status": "FAIL"}]}
        ],
        "observations": {
            "runner_status": "COMPLETE",
            "protocol": exp.experimental_protocol,
            "native_results": native,
            "selection_history": {
                "holdout_status": "UNOBSERVED_DECLARED" if holdout == "UNOBSERVED" else holdout
            },
        },
        "references": {
            k: {"path": "C:/Users/private/" + str(i), "sha256": sha(raw)}
            for i, (k, raw) in enumerate(documents.items())
        },
        "blockers": ["No independent economic validation; no demo/paper review eligibility."],
        "uncertainties": ["Prospective significance and model risk remain unverified"],
        "recommended_next_test": "Human review of preserved evidence",
        "scope_of_verification": ["Synthetic prior audit; no backtest executed"],
    }
    verdict.update(verdict_updates or {})
    verdict = AuditVerdict.model_validate_json(canonical(verdict)).model_dump(mode="json")
    raw = canonical(verdict).encode()
    source = PreparedAudit(
        raw,
        expected_sha256=sha(raw),
        documents=tuple(AuditDocument(k, v) for k, v in documents.items()),
        case_bindings={c.id: c.id for c in rows},
    )
    request = {
        "schema_version": "1.0",
        "contract_kind": "ValidationRequest",
        "request_id": "validation_01",
        "source_run_ids": [run_id],
        "audits": [
            {
                "run_id": run_id,
                "audit_id": "audit_fixture" if run_id == "r" else "audit_" + run_id,
                "verdict_sha256": sha(raw),
            }
        ],
        "expected_checkpoint": None,
    }
    return {
        "store": store,
        "bundle": bundle,
        "source": source,
        "sources": (source,),
        "raw_verdict": raw,
        "verdict": verdict,
        "documents": documents,
        "request": request,
        "root": root,
    }


@pytest.fixture
def fixture_factory(tmp_path):
    made = []

    def make(*, paired=False, second_updates=None, **kwargs):
        root = tmp_path / f"fixture-{len(made)}"
        data = create_fixture(root, **kwargs)
        if paired:
            other = create_fixture(
                root / "secondary", run_id="r2", **{**kwargs, **(second_updates or {})}
            )
            with data["store"].connection(write=True) as conn:
                for table in ("runs", "case_results", "artifacts", "research_decisions"):
                    refs = REFERENCES[table]
                    for record in other["bundle"].model_dump(mode="json")[table]:
                        columns = ["id", "payload", "sha256", "registered_at_utc", *refs]
                        values = [
                            record["id"],
                            canonical(record),
                            fingerprint(record),
                            now(),
                            *(record[k] for k in refs),
                        ]
                        conn.execute(
                            f"INSERT INTO {table}({','.join(columns)}) VALUES("
                            + ",".join("?" for _ in values)
                            + ")",
                            values,
                        )
                        if table in ("runs", "case_results") and kwargs.get("source_audited", True):
                            Store._event(
                                conn,
                                "SOURCE_AUDITED_" + table,
                                "synthetic second run",
                                fingerprint(record),
                            )
                        if table == "artifacts" and kwargs.get("hash_verified", True):
                            Store._event(
                                conn,
                                "HASH_VERIFIED_artifacts",
                                "synthetic second run",
                                fingerprint(record),
                            )
            data["sources"] = (data["source"], other["source"])
            data["request"]["source_run_ids"].append("r2")
            data["request"]["audits"].extend(other["request"]["audits"])
        made.append((data, inventory(data["store"].path.parent)))
        return data

    yield make
    for data, before in made:
        assert inventory(data["store"].path.parent) == before
        assert sha(data["raw_verdict"]) == data["source"].snapshot()["expected_sha256"]
        assert not any(
            p.name.endswith(("-wal", "-shm", "-journal"))
            for p in data["store"].path.parent.iterdir()
        )


@pytest.fixture
def dossier(fixture_factory):
    return fixture_factory()


@pytest.fixture
def exercise(record_property):
    def run(data, *, provider=None, book=None, context=None, request=None):
        provider = provider or FakeValidatorProvider()
        book = book or ReceiptBook()
        agent = QuantValidator(
            context or ValidatorContext(data["store"].path, fixture_root=data["root"]),
            provider,
            book,
        )
        raw = request if type(request) is bytes else canonical(request or data["request"]).encode()
        result = agent.run(raw, sources=data["sources"])
        record_property("validator_status", result["status"])
        record_property("validator_error", result["error_code"] or "NONE")
        record_property("validator_context_bytes", result["receipt"]["context_bytes"])
        record_property("validator_response_bytes", result["receipt"]["response_bytes"])
        record_property("validator_queries", canonical(result["receipt"]["catalogue_metrics"]))
        return result, agent, provider, book

    return run


@pytest.fixture(autouse=True)
def fake_measurements(monkeypatch, record_property):
    original, sizes = FakeValidatorProvider.respond, []

    def respond(self, packet):
        sizes.append(len(packet))
        return original(self, packet)

    monkeypatch.setattr(FakeValidatorProvider, "respond", respond)
    yield
    record_property("measured_validator_calls", len(sizes))
    record_property("measured_validator_context_bytes", canonical(sizes))
