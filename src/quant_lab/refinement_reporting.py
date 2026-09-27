"""Predeclared operational gates and paired confirmation reports."""

import pandas as pd

from quant_lab.cross_market_study import clean_json
from quant_lab.experiments import write_json
from quant_lab.mtf_reporting import classify
from quant_lab.study_report import markdown

PAPER_RULES = {
    "scope": "Operational only; never replaces historical classification; no paper launch.",
    "absolute": "Full BASE expectancy>0, PF>1, Sharpe>0; full ADVERSE return>0; "
    "validation/test/holdout BASE return>0; >=50% positive WF TEST "
    "folds; full and holdout>=30 trades.",
    "relative": "No deterioration versus paired baseline in full BASE drawdown, "
    "expectancy, PF, cost drag (ZERO minus BASE percentage points), "
    "positive WF fraction, holdout return, holdout expectancy or "
    "holdout drawdown.",
    "materiality": "Conservative zero deterioration allowance (1e-9 numerical "
    "tolerance), fixed before run; no subjective materiality "
    "threshold.",
    "technical": "All mandatory tests, deterministic replay, cohort identity and "
    "exact baseline replay must pass. MARGIN_MODEL_ASSUMED retained. "
    "Low sample cannot become a candidate in this phase.",
}


def paper_gate(refined, baseline, hold, base_hold):
    failures = []

    def require(ok, reason):
        if not bool(ok):
            failures.append(reason)

    for key, limit in (("expectancy", 0), ("profit_factor", 1), ("sharpe", 0)):
        require(pd.notna(refined[key]) and refined[key] > limit, key)
    require(refined["adverse_return"] > 0, "adverse_cost_edge")
    for p in ("validation", "test", "final_holdout"):
        require(refined[p] > 0, p)
    require(refined["wf_positive_fold_ratio"] >= 0.5, "wf_fraction")
    require(
        refined["closed_trades"] >= 30 and hold["closed_trades"] >= 30,
        "sample_below_existing_minimum",
    )
    for key, up in (
        ("max_drawdown_pct", False),
        ("expectancy", True),
        ("profit_factor", True),
        ("wf_positive_fold_ratio", True),
    ):
        a, b = refined[key], baseline[key]
        require(
            pd.notna(a) and pd.notna(b) and (a >= b - 1e-9 if up else a <= b + 1e-9),
            "relative_" + key,
        )
    require(
        refined["zero_return"] - refined["return_pct"]
        <= baseline["zero_return"] - baseline["return_pct"] + 1e-9,
        "relative_cost_drag",
    )
    for key, up in (("return_pct", True), ("expectancy", True), ("max_drawdown_pct", False)):
        a, b = hold[key], base_hold[key]
        require(
            pd.notna(a) and pd.notna(b) and (a >= b - 1e-9 if up else a <= b + 1e-9),
            "relative_holdout_" + key,
        )
    return {
        "operational_label": "PAPER_TRADING_CANDIDATE" if not failures else "ARCHIVE_NO_PAPER",
        "failed_operational_gates": failures,
    }


def finish(path, rows):
    f = pd.DataFrame(rows)
    f.to_csv(path / "results.csv", index=False)
    f.to_csv(path / "metrics.csv", index=False)
    f[f.partition.str.startswith("segment_")].to_csv(path / "segment_metrics.csv", index=False)
    full = classify(f)
    holding = f[(f.partition == "final_holdout") & (f.costs == "base")].copy()
    holding.to_csv(path / "holdout.csv", index=False)
    f[
        [
            "asset",
            "family",
            "architecture",
            "partition",
            "costs",
            "fees",
            "slippage_cost",
            "spread_cost",
            "funding_pnl",
            "total_costs",
            "return_pct",
        ]
    ].to_csv(path / "costs.csv", index=False)
    temporal = []
    pairs = []
    operational = []
    measure_map = {
        "return": "return_pct",
        "sharpe": "sharpe",
        "drawdown": "max_drawdown_pct",
        "profit_factor": "profit_factor",
        "expectancy": "expectancy",
        "trades": "closed_trades",
        "costs": "total_costs",
        "exposure": "time_in_market_pct",
    }
    for (asset, family), group in full.groupby(["asset", "family"]):
        baseline = group[~group.architecture.str.endswith(".1")].iloc[0]
        refined = group[group.architecture.str.endswith(".1")].iloc[0]
        for _, r in group.iterrows():
            wf = f[
                (f.asset == asset)
                & (f.family == family)
                & (f.architecture == r.architecture)
                & (f.costs == "base")
                & f.partition.str.startswith("wf_")
            ]
            temporal.append(
                {
                    "asset": asset,
                    "family": family,
                    "architecture": r.architecture,
                    "positive_folds": int((wf.return_pct > 0).sum()),
                    "negative_folds": int((wf.return_pct < 0).sum()),
                    "zero_folds": int((wf.return_pct == 0).sum()),
                    "failed_folds": 0,
                    "consistency_ratio": r.wf_positive_fold_ratio,
                }
            )
        hold = holding[
            (holding.asset == asset)
            & (holding.family == family)
            & (holding.architecture == refined.architecture)
        ].iloc[0]
        bh = holding[
            (holding.asset == asset)
            & (holding.family == family)
            & (holding.architecture == baseline.architecture)
        ].iloc[0]
        gate = paper_gate(refined, baseline, hold, bh)
        operational.append(
            {
                "asset": asset,
                "family": family,
                "architecture": refined.architecture,
                "historical_classification": refined.classification,
                **gate,
            }
        )
        pair = {
            "asset": asset,
            "family": family,
            "baseline": baseline.architecture,
            "refined": refined.architecture,
            **gate,
        }
        for label, column in measure_map.items():
            a, b = refined[column], baseline[column]
            pair["delta_" + label] = a - b if pd.notna(a) and pd.notna(b) else None
        pair.update(
            holdout_return=hold.return_pct,
            holdout_trades=int(hold.closed_trades),
            holdout_expectancy=hold.expectancy,
            holdout_profit_factor=hold.profit_factor,
            holdout_max_drawdown=hold.max_drawdown_pct,
            delta_holdout_return=hold.return_pct - bh.return_pct,
        )
        pairs.append(pair)
    full.to_csv(path / "comparison.csv", index=False)
    pd.DataFrame(pairs).to_csv(path / "paired_deltas.csv", index=False)
    pd.DataFrame(temporal).to_csv(path / "temporal_validation.csv", index=False)
    write_json(
        path / "paper_trading_candidates.json",
        clean_json({"rules": PAPER_RULES, "configurations": operational}),
    )
    cols = [
        "asset",
        "family",
        "architecture",
        "return_pct",
        "sharpe",
        "max_drawdown_pct",
        "profit_factor",
        "expectancy",
        "closed_trades",
        "total_costs",
        "classification",
    ]
    signals = [
        "signals_generated",
        "signals_executed",
        "signals_expired",
        "signals_invalidated",
        "signals_consumed",
        "duplicate_entries_prevented",
        "cooldown_entries_blocked",
        "extension_entries_blocked",
        "average_time_to_entry",
        "trades_per_signal",
    ]
    sections = [
        "# Execution refinement confirmation",
        "## Objective\nArchitecture and execution only. Four explicitly "
        "requested pairs; no indicator tuning. Observed historical "
        "cohort, not fresh OOS.",
        "## Exact changes\nV2.1 preserves V2 signals and adds lifecycle, "
        "one-hour cooldown and 1.5 ATR opening-distance guard. V4.1 "
        "freezes the V2 Bollinger hourly opportunity and uses the "
        "historical V4 quarter-hour recovery only to time execution. A "
        "post-origin pullback is required. Four quarter closes, including"
        " the expiry boundary, are eligible. Stops use the frozen hourly "
        "ATR. No dynamic spread is invented.",
        f"## Comparison\n{len(f)} independent executions; inherited 10,000 USDT, "
        "costs, funding, margin, segments and folds. "
        "Baseline replay must match MTF03 exactly.\n" + markdown(full, cols),
        "## Paired deltas\nRefined minus baseline. Negative cost/drawdown "
        "deltas indicate a reduction.\n"
        + markdown(
            pd.DataFrame(pairs),
            ["asset", "family", *["delta_" + k for k in measure_map], "delta_holdout_return"],
        ),
        "## Signal diagnostics\nBlocking counters count attempts, not "
        "unique signals. Ages/delays are hours; distances are ATR units. "
        "Baseline lifecycle is observation only; disabled guards are "
        "null, not claimed prevention.\n"
        + markdown(full, ["asset", "family", "architecture", *signals]),
        "## Costs\nZERO disables fees and funding; BASE/ADVERSE retain "
        "identical actual funding rates. Total costs include net funding "
        "cost, which can be a credit. Full per-scenario rows are in "
        "costs.csv; cost sensitivity and classifications are unchanged.",
        "## Temporal stability\n" + markdown(pd.DataFrame(temporal), list(temporal[0])),
        "All 29 continuous segment comparisons are in "
        "segment_metrics.csv. Segment returns are independent accounts "
        "and cannot be summed. Failed folds would abort the batch rather "
        "than disappear from an average.",
        "## Holdout\n"
        + markdown(
            holding,
            [
                "asset",
                "family",
                "architecture",
                "return_pct",
                "closed_trades",
                "expectancy",
                "profit_factor",
                "max_drawdown_pct",
            ],
        ),
        "## Operational conclusions\n"
        + markdown(
            pd.DataFrame(operational),
            ["asset", "family", "architecture", "operational_label", "failed_operational_gates"],
        ),
        "Operational labels are separate from historical classifications."
        " No paper process is launched. Remaining risks: already-observed"
        " cohort/selection, assumed historical margin tiers, fixed spread"
        " rather than observed quotes, insufficient holdout samples where"
        " flagged, and no demonstrated out-of-sample edge.",
    ]
    (path / "summary.md").write_text("\n\n".join(sections) + "\n", encoding="utf-8")
    (path / "paper_trading_candidates.md").write_text(
        "# Operational paper assessment\n\n"
        + markdown(pd.DataFrame(operational), list(operational[0]))
        + "\n\nNo paper trading started. Exact predeclared gates are in plan.json.\n",
        encoding="utf-8",
    )
    (path / "diagnostics.md").write_text(
        "# Lifecycle conventions\n\nFrozen signal origins are immutable. "
        "Entry callbacks consume only successful fills. Opening decisions"
        " receive no current high, low or close. Intrabar exits become "
        "known at bar close for cooldown. One valid V2 hourly close is "
        "one distinct opportunity; the historical engine already "
        "prevented pyramiding, so this is not a claim that its positions "
        "were duplicated. V4.1 cannot create 15m opportunities. Signals "
        "do not carry across gaps/windows; features reset after physical "
        "gaps. Frozen hourly ATR controls risk and extension. Extension "
        "uses absolute next-open distance from signal close; reported "
        "fill distance includes modeled execution costs. Spread guarding "
        "requires observed quotes and an explicit limit and is disabled "
        "for this dataset. Signals are prioritized oldest-first at the "
        "shared expiry/new-hour boundary. Baseline engine signal_close "
        "denotes execution-trigger availability; origin_signal_timestamp "
        "in trades.csv identifies the earlier frozen V4.1 origin. Signals"
        " and lifecycle rows are scoped by experiment_id.\n",
        encoding="utf-8",
    )
    return full, pairs, operational
