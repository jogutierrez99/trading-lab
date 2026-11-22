"""An existing deterministic Auditor prepares the synthetic evidence unchanged.

The inherited step-4.4 fixture simulates only the step-4.3 implementation seal;
its native identity, hash, metric and denominator checks run normally. No runner,
model, notification transport or real database is involved.
"""

import sqlite3
from pathlib import Path

from tests.unit.test_audit_orchestration import audited, fixture, reseal_fixture
from trading_lab_agents.receipts import ReceiptBook
from trading_lab_agents.validator import QuantValidator
from trading_lab_agents.validator_context import ValidatorContext
from trading_lab_agents.validator_evidence import AuditDocument, PreparedAudit
from trading_lab_agents.validator_provider import FakeValidatorProvider
from trading_lab_catalog.models import Artifact, Bundle, Case, Experiment, Run, Strategy, Version
from trading_lab_catalog.store import Store
from trading_lab_catalog.verification import parse, sha
from trading_lab_orchestration.contracts import canonical

from .conftest import inventory


def test_existing_deterministic_audit_to_consultative_validator(tmp_path, monkeypatch):
    prior = fixture.__wrapped__(tmp_path / "prior", monkeypatch)
    costs = {"trading_fee_pct": 0.05, "slippage_pct": 0.03, "spread_pct": 0.01}
    with sqlite3.connect(prior.run / "ledger.sqlite") as connection:
        for index, segment in enumerate(("train", "validation", "test")):
            p = prior.run / segment / "result.json"
            result = parse(p.read_bytes())
            metadata = {
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "mode": "LONG_ONLY",
                "period": segment,
                "scenario": "BASE",
                "start": f"2024-0{index + 1}-01T00:00:00Z",
                "end": f"2024-0{index + 2}-01T00:00:00Z",
                "costs": costs,
                "parameters": {"window": 20},
            }
            result["metrics"].update(metadata)
            result["metrics"].update(
                return_pct=0.0, max_drawdown_pct=0.0, win_rate_pct=None, starting_equity=10000.0
            )
            raw = canonical(result).encode()
            p.write_bytes(raw)
            connection.execute(
                "UPDATE experiments SET result_sha256=?,metadata=? WHERE id=?",
                (sha(raw), canonical(metadata), segment),
            )
    reseal_fixture(prior)
    output = audited(prior)
    assert output["status"] == "COMPLETED_WITH_LIMITATIONS", output
    v = output["verdict"]
    raw = (Path(output["root"]) / "audit_verdict.json").read_bytes()
    documents = tuple(
        AuditDocument(key, Path(ref["path"]).read_bytes()) for key, ref in v["references"].items()
    )
    source = PreparedAudit(
        raw,
        expected_sha256=sha(raw),
        documents=documents,
        case_bindings={
            r["backtest_id"]: r["backtest_id"] for r in v["observations"]["native_results"]
        },
    )
    run_id, experiment_id = v["run_id"], v["experiment_id"]
    strategy = Strategy(
        id="s", name="Synthetic audited fixture", description="Fixture only", source="fixture"
    )
    version = Version(
        id="v",
        strategy_id="s",
        semantic_version="1.0.0",
        implementation_reference="fixture",
        code_sha256="a" * 64,
    )
    holdout = v["observations"]["selection_history"]["holdout_status"]
    exp = Experiment(
        id=experiment_id,
        version_id="v",
        hypothesis="Synthetic hypothesis",
        market_type="spot",
        asset="BTCUSDT",
        timeframe="1h",
        direction="LONG_ONLY",
        parameters={"window": 20},
        configuration_sha256=prior.request.resolved_configuration_sha256,
        dataset_sha256=prior.request.dataset_manifest_sha256["fixture"],
        experimental_protocol=v["observations"]["protocol"],
        risk={"risk_per_trade_pct": 0.5},
        execution_assumptions={"entry_timing": "NEXT_OPEN"},
        holdout="UNOBSERVED" if holdout == "UNOBSERVED_DECLARED" else holdout,
        capital_policy="RESET_PER_SEGMENT",
    )
    run = Run(
        id=run_id,
        experiment_id=experiment_id,
        engine="synthetic_fixture",
        engine_version="1",
        job_sha256=sha((prior.root / "request.json").read_bytes()),
        status="COMPLETE",
        kind="SYNTHETIC",
        evidence_reference="private host reference",
        evidence_sha256=v["references"]["execution_receipt"]["sha256"],
        audit_status="UNVERIFIED",
    )
    cases = []
    for r in v["observations"]["native_results"]:
        m = r["result"]["metrics"]
        cases.append(
            Case.model_validate_json(
                canonical(
                    {
                        "id": r["backtest_id"],
                        "run_id": run_id,
                        "segment": m["period"],
                        "scenario": m["scenario"],
                        "period_start_utc": m["start"],
                        "period_end_utc": m["end"],
                        "warmup_bars": 240,
                        "trades": 0,
                        "net_return_pct": m["return_pct"],
                        "max_drawdown_pct": m["max_drawdown_pct"],
                        "win_rate_pct": None,
                        "profit_factor": None,
                        "capital_initial": m["starting_equity"],
                        "costs": costs,
                        "metrics": {"sharpe": None},
                        "audit_status": "UNVERIFIED",
                    }
                )
            )
        )
    artifact = Artifact(
        id="a",
        run_id=run_id,
        artifact_type="metrics_csv",
        reference="private host reference",
        sha256=v["references"]["native:metrics.csv"]["sha256"],
        verification_status="UNVERIFIED",
    )
    catalogue = Store(tmp_path / "consultation" / "strategy-catalog.sqlite3")
    catalogue.init()
    catalogue.ingest(
        Bundle(
            strategies=[strategy],
            versions=[version],
            experiments=[exp],
            runs=[run],
            case_results=cases,
            artifacts=[artifact],
        ),
        source="synthetic host bridge",
    )
    protected_before = inventory(tmp_path)
    request = {
        "schema_version": "1.0",
        "contract_kind": "ValidationRequest",
        "request_id": "audit_bridge",
        "source_run_ids": [run_id],
        "audits": [{"run_id": run_id, "audit_id": v["audit_id"], "verdict_sha256": sha(raw)}],
        "expected_checkpoint": None,
    }
    provider = FakeValidatorProvider()
    validator = QuantValidator(
        ValidatorContext(catalogue.path, fixture_root=tmp_path), provider, ReceiptBook()
    )
    result = validator.run(canonical(request).encode(), sources=(source,))
    assert result["status"] == "COMPLETE", result
    assert result["assessment"]["status"] == "NEEDS_REVIEW"  # no accreditation minted
    assert result["assessment"]["model_review"]["verdict"] == v["auditor_verdict"] == "NO_DECISION"
    assert result["receipt"]["source_verdict_sha256"] == [sha(raw)]
    assert inventory(tmp_path) == protected_before and provider.calls == 1
