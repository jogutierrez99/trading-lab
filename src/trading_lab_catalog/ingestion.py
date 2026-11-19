"""Issue #3 export adapter. Sealed receipt is required as an explicit trust anchor."""

import base64
import csv
import io
from pathlib import Path

from .models import (
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
)
from .verification import BlockedSource, parse, read, sha


def preview(source, sealed_source, receipt_sha256):
    try:
        return _preview(Path(source), Path(sealed_source), receipt_sha256)
    except (ValueError, OSError, KeyError, TypeError, StopIteration) as exc:
        raise BlockedSource("Source contract, hash or sealed evidence mismatch") from exc


def _preview(source, sealed_source, receipt_sha256):
    # The adapter imports contracts only; it never loads or calls the historical runner.
    from trading_lab_orchestration.historical_pilot_contract import (
        Job,
        decode_transport,
        plan_sha,
    )

    manifest_bytes = read(source / "manifest.json")
    manifest = parse(manifest_bytes)
    expected = {
        "summary.json",
        "metrics.csv",
        "trades.csv",
        "source-hashes.json",
        "informe.md",
        "train_base.json",
        "train_adverse.json",
        "validation_base.json",
        "validation_adverse.json",
        "test_retrospective_base.json",
        "test_retrospective_adverse.json",
    }
    if set(manifest) != expected or {p.name for p in source.iterdir()} != expected | {
        "manifest.json"
    }:
        raise BlockedSource("Unexpected export members")
    captured = {name: read(source / name) for name in expected}
    if any(sha(raw) != manifest[name] for name, raw in captured.items()):
        raise BlockedSource("Export hash mismatch")
    sealed_bytes = read(sealed_source)
    if sha(sealed_bytes) != receipt_sha256:
        raise BlockedSource("Sealed receipt does not match the reviewed trust anchor")
    sealed, summary = parse(sealed_bytes), parse(captured["summary.json"])
    sources = parse(captured["source-hashes.json"])
    job = Job.model_validate_json(canonical(sealed["job"]))
    if (
        job.mode != "HISTORICAL"
        or sealed["status"] != "COMPLETE"
        or sealed["job_sha256"] != plan_sha(job)
        or summary["job_sha256"] != plan_sha(job)
        or summary["host_receipt_sha256"] != receipt_sha256
        or sources["result_sha256"] != receipt_sha256
        or summary["audit"] != sealed["audit"]
        or summary["registry_state"] != "SEALED"
        or summary["strategy"] != job.plan.strategy
        or summary["image"] != job.plan.image
        or summary["holdout"] != job.plan.holdout
    ):
        raise BlockedSource("Contradictory sealed identity")
    transport = base64.b64decode(sealed["stdout"], validate=True)
    if sha(transport) != sealed["stdout_sha256"] or sources["transport_sha256"] != sha(transport):
        raise BlockedSource("Transport changed")
    decoded = list(decode_transport(transport, job))
    if len(decoded) != 6:
        raise BlockedSource("Six cases required")
    metrics_rows = list(csv.DictReader(io.StringIO(captured["metrics.csv"].decode())))
    trades_rows = list(csv.DictReader(io.StringIO(captured["trades.csv"].decode())))
    if len(metrics_rows) != 6 or len({r["case"] for r in metrics_rows}) != 6:
        raise BlockedSource("Repeated or missing CSV cases")
    strategy_id = job.plan.strategy
    version_id = "version-" + fingerprint(job.plan.input_files)
    experiment_id = "experiment-" + fingerprint(job.plan.model_dump(mode="json"))
    run_id = "run-" + receipt_sha256
    config = fingerprint(job.plan.model_dump(mode="json"))
    cases, expected_trades = [], []
    for case, member in decoded:
        if parse(captured[case.id + ".json"]) != member.model_dump(mode="json"):
            raise BlockedSource("Case differs from sealed transport")
        row = next(r for r in metrics_rows if r["case"] == case.id)
        summary_row = next(r for r in summary["cases"] if r["case"] == case.id)
        expected_row = dict(
            case=case.id,
            segment=case.segment,
            scenario=case.scenario,
            start=case.start.isoformat(),
            end_exclusive=case.end.isoformat(),
            warmup=case.warmup,
            **member.metrics.model_dump(mode="json"),
        )
        if summary_row != expected_row or set(row) != set(expected_row):
            raise BlockedSource("Export metadata differs from sealed case")
        for key in ("segment", "scenario", "start", "end_exclusive", "warmup"):
            if row[key] != str(expected_row[key]):
                raise BlockedSource("CSV metadata differs from sealed case")
        for key, value in member.metrics.model_dump(mode="json").items():
            if (None if row[key] == "" else float(row[key])) != value or summary_row[key] != value:
                raise BlockedSource("CSV metrics differ from sealed case")
        if sealed["audit"]["metrics"][case.id] != member.metrics.model_dump(mode="json"):
            raise BlockedSource("Source audit differs from case")
        for number, trade in enumerate(member.trades, 1):
            expected_trades.append(
                {
                    "case": case.id,
                    "trade_number": str(number),
                    **{
                        k: "" if v is None else str(v)
                        for k, v in trade.model_dump(mode="json").items()
                    },
                }
            )
        m = member.metrics
        cases.append(
            Case(
                id=run_id + "." + case.id,
                run_id=run_id,
                segment=case.segment,
                scenario=case.scenario,
                period_start_utc=case.start,
                period_end_utc=case.end,
                warmup_bars=case.warmup,
                trades=m.closed_trades,
                net_return_pct=m.return_pct,
                max_drawdown_pct=m.max_drawdown_pct,
                win_rate_pct=m.win_rate_pct,
                profit_factor=m.profit_factor,
                capital_initial=job.plan.risk.initial_cash,
                costs=case.costs.model_dump(mode="json"),
                metrics=m.model_dump(mode="json"),
                audit_status="SOURCE_AUDITED",
            )
        )
    if trades_rows != expected_trades:
        raise BlockedSource("CSV trades differ from sealed cases")
    if summary["audit"]["economic_decision"] != "NO_DECISION":
        raise BlockedSource("Unexpected economic decision for this adapter")
    artifacts = [
        Artifact(
            id="artifact-" + fingerprint([run_id, name]),
            run_id=run_id,
            artifact_type=name,
            reference=str((source / name).absolute()),
            sha256=manifest[name],
            verification_status="HASH_VERIFIED",
        )
        for name in sorted(expected)
    ]
    artifacts.append(
        Artifact(
            id="artifact-" + receipt_sha256,
            run_id=run_id,
            artifact_type="SEALED_RECEIPT",
            reference=str(sealed_source.absolute()),
            sha256=receipt_sha256,
            verification_status="HASH_VERIFIED",
        )
    )
    return Bundle(
        strategies=[
            Strategy(id=strategy_id, name=strategy_id, description=strategy_id, source="quant_lab")
        ],
        versions=[
            Version(
                id=version_id,
                strategy_id=strategy_id,
                semantic_version=None,
                implementation_reference=strategy_id,
                git_commit=job.plan.code_commit,
                code_sha256=job.plan.input_files[f"src/quant_lab/strategies/{strategy_id}.py"],
                configuration_sha256=config,
            )
        ],
        experiments=[
            Experiment(
                id=experiment_id,
                version_id=version_id,
                hypothesis="Frozen Issue #3",
                market_type="spot",
                asset=job.plan.symbol,
                timeframe=job.plan.timeframe,
                direction="LONG_ONLY",
                parameters=job.plan.parameters,
                configuration_sha256=config,
                dataset_sha256=job.plan.dataset_sha256,
                experimental_protocol="StudyBackend v1 Issue #3",
                risk=job.plan.risk.model_dump(mode="json"),
                execution_assumptions={"protocol_sha256": job.plan.protocol_sha256},
                holdout="CONSUMED",
                capital_policy="RESET_PER_SEGMENT",
            )
        ],
        runs=[
            Run(
                id=run_id,
                experiment_id=experiment_id,
                engine=job.plan.engine,
                engine_version="1",
                execution_commit=summary["commit"],
                job_sha256=plan_sha(job),
                status="COMPLETE",
                kind="HISTORICAL",
                evidence_reference=str(sealed_source.absolute()),
                evidence_sha256=receipt_sha256,
                audit_status="SOURCE_AUDITED",
            )
        ],
        case_results=cases,
        artifacts=artifacts,
        research_decisions=[
            Decision(
                id="decision-" + receipt_sha256,
                strategy_id=strategy_id,
                version_id=version_id,
                run_id=run_id,
                category="ECONOMIC",
                verdict="NO_DECISION",
                reasoning="Preserved sealed source verdict",
                limitations=["Small sample", "Holdout consumed"],
                decided_by="sealed deterministic audit",
                decided_at_utc=None,
            )
        ],
    )
