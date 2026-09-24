"""Immutable cross_market_timeframe_study_001 orchestration with resumable ledger."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from quant_lab.batch import COSTS
from quant_lab.batch_003_analysis import extended_metrics
from quant_lab.batch_004_analysis import monte_carlo
from quant_lab.config import StrategyConfig
from quant_lab.execution_config import ExecutionConfig
from quant_lab.experiments import ExperimentStore, provenance, write_json
from quant_lab.metrics import summarize
from quant_lab.strategies.registry import StrategyRegistry
from quant_lab.study_analysis import (
    CLASSIFICATION,
    consistency,
    correlations,
    cost_rows,
    flags,
    overlaps,
    stability,
)
from quant_lab.study_data import HOURS
from quant_lab.study_excursions import entry_diagnostics
from quant_lab.study_execution import annual_windows, attribution, execute, prepare_blocks
from quant_lab.study_plan import datasets, frozen_configs, matrix, translation_document, windows

NAME = "cross_market_timeframe_study_001"


def protect(repo):
    snapshot = json.loads((repo / "reports" / NAME / "protected_previous.json").read_text())
    changed = [
        p
        for p, sha in snapshot.items()
        if not (repo / p).exists() or hashlib.sha256((repo / p).read_bytes()).hexdigest() != sha
    ]
    if changed:
        raise ValueError(f"Protected previous artifacts changed: {changed[:10]}")
    return {"files": len(snapshot), "unchanged": True}


def execution_config(asset):
    return ExecutionConfig(
        quantity_step=0.00001 if asset == "BTCUSDT" else 0.0001,
        min_quantity=0.00001 if asset == "BTCUSDT" else 0.0001,
        min_notional=10.0,
        filter_assumption=(
            "Fixed research lot/minimum assumptions, not verified historical "
            "exchange filters. No orders."
        ),
    )


def clean_json(value):
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def run(repo: Path, resume: Path | None = None):
    protected = protect(repo)
    frames, audits = datasets(repo)
    configs = frozen_configs(repo)
    combinations = matrix(configs)
    first = frames["BTCUSDT/1h"].index[0]
    end = frames["BTCUSDT/1h"].index[-1] + pd.Timedelta(hours=1)
    splits = windows(first, end)
    code = provenance(repo)
    preflight = json.loads((repo / "reports" / NAME / "preflight.json").read_text())
    if preflight["code_sha256"] != code["code_sha256"] or any(
        preflight[c]["exit_code"]
        for c in ("pytest -q", "ruff check .", "ruff format --check .", "pip check")
    ):
        raise ValueError("Preflight tests absent, failed or stale")
    plan = {
        "study": NAME,
        "strategies": configs,
        "matrix": combinations,
        "datasets": audits,
        "splits": [(n, str(a), str(b)) for n, a, b in splits],
        "costs": {k: v.model_dump() for k, v in COSTS.items()},
        "execution": {a: execution_config(a).model_dump() for a in ("BTCUSDT", "ETHUSDT")},
        "translation": translation_document(configs),
        "classification": CLASSIFICATION,
        "capital": (
            "10000USDT per strategy/asset/timeframe/partition/scenario. No "
            "portfolio. Flat cash persists between disjoint segments of ONE "
            "run; positions and features reset at every gap."
        ),
        "analysis": (
            "Complete frozen matrix; NO selection. All split/cost runs first, "
            "final_holdout after ALL train/validation/test. Full-period and "
            "independent annual reruns afterwards. Annual stability excludes "
            "partial calendar years. Annual windows have causal warmup within "
            "contiguous data only."
        ),
        "labels": (
            "ETH: CROSS_ASSET_VALIDATION under frozen temporal adapter. BTC: "
            "REUSED_HISTORY_DIAGNOSTIC, with separate2026 new-period "
            "diagnostic. BTC pre2026 includes previously observed intervals; "
            "never clean OOS."
        ),
        "monte_carlo": (
            "Only full-period BASE combinations,>=30 "
            "trades,10000reshufflings+10000bootstraps fixed cash PnLs; SHA256 "
            "deterministic seeds. No ranking."
        ),
        "excursions": (
            "All runs; lower/upper intrabar MFE/MAE bounds; timing uncertainty"
            " actual bar duration. Edge1/3/6/12/24bars and24/72/168hours; "
            "censor crossing gaps or window end."
        ),
        "regimes": (
            "EMA50/200 bars; sideways absolute distance<=0.25%. ATR14/close "
            "versus previous30days quantiles30/70. Trade attribution at prior "
            "signal close; barPnL at preceding close. No feedback."
        ),
        "overlap": (
            "Executed entry-time Jaccard and occupied-bar Jaccard within same "
            "asset/timeframe, full/base only. Not raw unfilled signal overlap."
        ),
        "preflight": preflight,
        "protected_previous": protected,
    }
    if resume:
        store = ExperimentStore.__new__(ExperimentStore)
        store.path, store.run_id = resume, resume.name
        old_code = json.loads((resume / "provenance.json").read_text())
        if old_code["code_sha256"] != code["code_sha256"]:
            raise ValueError("Cannot resume with changed code; create a new experiment")
        frozen = json.loads((resume / "plan.json").read_text())
        if frozen["datasets"] != plan["datasets"]:
            raise ValueError("Cannot resume changed datasets")
    else:
        store = ExperimentStore(repo / "results" / NAME, plan, code)
        write_json(store.path / "dataset_audit.json", audits)
        inventory = pd.DataFrame(audits["raw"].values())
        inventory.to_csv(store.path / "dataset_inventory.csv", index=False)
        (store.path / "timeframe_translation.md").write_text(plan["translation"], encoding="utf-8")
        pd.DataFrame(combinations).to_csv(store.path / "matrix.csv", index=False)
    print(f"STUDY {store.path}", flush=True)
    registry = StrategyRegistry().discover()
    prepared = {}
    for c in combinations:
        if c["reason"]:
            continue
        cfg = StrategyConfig.model_validate_json(
            json.dumps(next(r["config"] for r in configs if r["candidate"] == c["candidate"]))
        )
        strategy = registry.create(cfg)
        key = (c["strategy"], c["asset"], c["timeframe"])
        prepared[key] = (
            strategy,
            prepare_blocks(strategy, frames[f"{c['asset']}/{c['timeframe']}"], c["timeframe"]),
        )
    done = {}
    with store.connect() as db:
        for id_, status, metadata in db.execute("SELECT id,status,metadata FROM experiments"):
            if status != "completed":
                raise ValueError(
                    f"Unfinished ledger item {id_}; retain failed experiment and create new run"
                )
            done[json.loads(metadata)["key"]] = id_
    all_windows = splits + [("full", first, end)] + list(annual_windows(first, end))
    for partition, start, stop in all_windows:
        if partition == "final_holdout" and not (store.path / "holdout_unlock.json").exists():
            expected = len(prepared) * 3 * 3
            if len(done) < expected:
                raise ValueError("Holdout locked: incomplete prior phases")
            write_json(
                store.path / "holdout_unlock.json",
                {
                    "completed_prior_runs": len(done),
                    "expected": expected,
                    "code_sha256": code["code_sha256"],
                    "rule": (
                        "All frozen combinations/costs through TEST; no selection or adaptation."
                    ),
                },
            )
        for c in combinations:
            if c["reason"]:
                continue
            strategy, blocks = prepared[(c["strategy"], c["asset"], c["timeframe"])]
            for scenario, costs in COSTS.items():
                key = "/".join((c["strategy"], c["asset"], c["timeframe"], partition, scenario))
                if key in done:
                    continue
                metadata = c | {
                    "key": key,
                    "partition": partition,
                    "costs": scenario,
                    "start": str(start),
                    "end": str(stop),
                }
                id_ = store.start(metadata)
                try:
                    result, labels = execute(
                        strategy,
                        blocks,
                        c["asset"],
                        c["timeframe"],
                        start,
                        stop,
                        costs,
                        execution_config(c["asset"]),
                    )
                    frame = frames[f"{c['asset']}/{c['timeframe']}"].loc[
                        start : stop - pd.Timedelta(hours=HOURS[c["timeframe"]])
                    ]
                    quality, edge, qm = entry_diagnostics(frame, result, c["timeframe"])
                    metrics = summarize(result) | extended_metrics(result) | qm
                    metrics["available_bars"] = len(frame)
                    metrics["excluded_bars"] = int(
                        (stop - start) / pd.Timedelta(hours=HOURS[c["timeframe"]])
                    ) - len(frame)
                    metrics["gross_positive_trade_pnl"] = sum(
                        max(0, t.quantity * (t.exit_reference - t.entry_reference))
                        for t in result.trades
                    )
                    if not np.isclose(
                        metrics["gross_pnl"] - metrics["total_costs"],
                        metrics["realized_net_pnl"],
                        atol=1e-6,
                    ):
                        raise AssertionError("Gross/net/cost reconciliation")
                    metrics["trades_per_year"] = metrics["closed_trades"] / (
                        metrics["observed_days"] / 365
                    )
                    document = {
                        "metadata": metadata,
                        "metrics": metrics,
                        "trades": [asdict(t) for t in result.trades],
                        "rejections": [asdict(r) for r in result.rejections],
                        "entry_quality": quality,
                        "time_to_edge": edge,
                        "regimes": attribution(result, labels, c["timeframe"]),
                    }
                    if partition == "full" and scenario == "base":
                        mc, arrays = monte_carlo([t.net_pnl for t in result.trades], key)
                        document["monte_carlo"] = mc
                        if arrays:
                            np.savez_compressed(
                                store.path / id_ / "monte_carlo_samples.npz", **arrays
                            )
                    pd.DataFrame({"equity": result.equity, "exposure": result.exposure}).to_parquet(
                        store.path / id_ / "equity.parquet"
                    )
                    store.finish(id_, clean_json(document))
                    done[key] = id_
                except Exception as exc:
                    store.finish(id_, {"error": str(exc)}, "failed")
                    raise
        print(f"COMPLETED {partition}: {len(done)} executions", flush=True)
    finalize(store, combinations)
    if provenance(repo)["code_sha256"] != code["code_sha256"]:
        raise ValueError("Code changed during frozen execution")
    verification = {
        "status": "completed",
        "executions": len(done),
        "evaluated_combinations": len(prepared),
        "skipped_combinations": len(combinations) - len(prepared),
        "protected_previous": protect(repo),
        "code_unchanged": True,
        "preflight": preflight,
        "aggregation": audits["aggregation_comparable"],
    }
    with store.connect() as db:
        for id_, sha in db.execute("SELECT id,result_sha256 FROM experiments"):
            if hashlib.sha256((store.path / id_ / "result.json").read_bytes()).hexdigest() != sha:
                raise AssertionError("Ledger hash mismatch")
    write_json(store.path / "verification.json", verification)
    from quant_lab.study_report import report

    report(store.path)
    print(f"COMPLETED STUDY {store.path}", flush=True)
    return store.path


def finalize(store, combinations):
    rows, full = [], {}
    with store.connect() as db:
        ids = [r[0] for r in db.execute("SELECT id FROM experiments WHERE status='completed'")]
    for id_ in ids:
        doc = json.loads((store.path / id_ / "result.json").read_text(encoding="utf-8"))
        meta = doc["metadata"]
        row = meta | doc["metrics"] | {"experiment_id": id_}
        row["complete_calendar_year"] = (
            meta["partition"].startswith("year_")
            and meta["start"][5:10] == "01-01"
            and meta["end"][5:10] == "01-01"
        )
        row["interpretation"] = (
            "CROSS_ASSET_VALIDATION"
            if meta["asset"] == "ETHUSDT"
            else "NEW_PERIOD_DIAGNOSTIC"
            if meta["partition"] == "year_2026"
            else "REUSED_HISTORY_DIAGNOSTIC"
        )
        rows.append(row)
        if meta["partition"] == "full" and meta["costs"] == "base":
            full[meta["key"]] = (id_, doc)
    table = pd.DataFrame(rows)
    table.to_csv(store.path / "metrics.csv", index=False)
    annual = table[table.partition.str.startswith("year_")].copy()
    annual["year"] = annual.partition.str[-4:].astype(int)
    annual.to_csv(store.path / "annual_metrics.csv", index=False)
    costs = cost_rows(table)
    write_json(store.path / "cost_analysis.json", clean_json(costs))
    base = table[(table.partition == "full") & (table.costs == "base")].copy()
    annual_base = annual[annual.costs == "base"]
    comparison, summaries = [], {}
    for strategy, group in base.groupby("strategy", sort=True):
        strategy_cost = [c for c in costs if c["strategy"] == strategy and c["partition"] == "full"]
        regimes = [
            doc["regimes"] for _, doc in full.values() if doc["metadata"]["strategy"] == strategy
        ]
        classification = flags(group, strategy_cost, regimes)
        summaries[strategy] = {
            "consistency_summary": consistency(
                group, annual_base[annual_base.strategy == strategy]
            ),
            "flags": classification,
        }
        for row in group.to_dict("records"):
            ys = annual_base[
                (annual_base.strategy == strategy)
                & (annual_base.asset == row["asset"])
                & (annual_base.timeframe == row["timeframe"])
            ]
            cost = next(
                c
                for c in strategy_cost
                if c["asset"] == row["asset"] and c["timeframe"] == row["timeframe"]
            )
            comparison.append(
                row
                | stability(ys)
                | {
                    "cost_drag": cost["zero_to_base_drag"],
                    "adverse_drag": cost["base_to_adverse_drag"],
                    "classification": ";".join(classification),
                    "status": "EVALUATED",
                }
            )
    comparison += [
        c | {"status": "NOT_EVALUABLE", "classification": "INSUFFICIENT_DATA;DIAGNOSTIC_ONLY"}
        for c in combinations
        if c["reason"]
    ]
    pd.DataFrame(comparison).to_csv(store.path / "timeframe_comparison.csv", index=False)
    write_json(store.path / "cross_asset_analysis.json", clean_json(summaries))
    for filename, field in (
        ("entry_quality", "entry_quality"),
        ("time_to_edge", "time_to_edge"),
        ("regime_analysis", "regimes"),
        ("monte_carlo", "monte_carlo"),
    ):
        write_json(
            store.path / (filename + ".json"), {k: doc[field] for k, (_, doc) in full.items()}
        )
    corr, overlap = {}, {}
    for asset in ("BTCUSDT", "ETHUSDT"):
        for tf in HOURS:
            selected = {
                doc["metadata"]["strategy"]: (id_, doc)
                for id_, doc in full.values()
                if doc["metadata"]["asset"] == asset and doc["metadata"]["timeframe"] == tf
            }
            corr[f"{asset}/{tf}"] = correlations(
                {
                    name: pd.read_parquet(store.path / id_ / "equity.parquet").equity
                    for name, (id_, _) in selected.items()
                }
            )
            overlap[f"{asset}/{tf}"] = overlaps(
                {name: doc["trades"] for name, (_, doc) in selected.items()}, tf
            )
    write_json(store.path / "correlations.json", corr)
    write_json(store.path / "signal_overlap.json", overlap)
