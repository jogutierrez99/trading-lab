"""Descriptive comparisons and the unchanged Batch006 eligibility criteria."""

import json

import pandas as pd

from quant_lab.cross_market_study import clean_json
from quant_lab.experiments import write_json
from quant_lab.study_report import markdown

KEYS = ["asset", "family", "architecture", "mode", "cohort"]


def classify(table: pd.DataFrame) -> pd.DataFrame:
    base = table[(table.partition == "full") & (table.costs == "base")].copy()
    rows = []
    for row in base.to_dict("records"):
        group = table
        for k in KEYS:
            group = group[group[k] == row[k]]
        parts = group[group.costs == "base"].set_index("partition")
        scenarios = group[group.partition == "full"].set_index("costs")
        wf = group[(group.costs == "base") & group.partition.str.startswith("wf_")]
        fraction = float((wf.return_pct > 0).mean())
        flags = ["DIAGNOSTIC_ONLY", "MARGIN_MODEL_ASSUMED"]
        if row["closed_trades"] < 30 or parts.loc["final_holdout", "closed_trades"] < 30:
            flags.append("INSUFFICIENT_DATA")
        if scenarios.loc["zero", "return_pct"] > 0 >= row["return_pct"]:
            flags.append("FAILED_AFTER_COSTS")
        if row["return_pct"] > 0 >= scenarios.loc["adverse", "return_pct"]:
            flags.append("COST_SENSITIVE")
        if any(parts.loc[p, "return_pct"] <= 0 for p in ("validation", "test", "final_holdout")):
            flags.append("FAILED_TEMPORAL_VALIDATION")
        elif (
            row["return_pct"] > 0
            and (row["profit_factor"] or 0) > 1
            and (row["sharpe"] or 0) > 0
            and parts.loc["final_holdout", "closed_trades"] >= 30
            and fraction >= 0.5
        ):
            flags.append("PROMISING_BUT_UNCONFIRMED")
        rows.append(
            row
            | {
                "classification": ";".join(flags),
                "wf_positive_fold_ratio": fraction,
                "zero_return": scenarios.loc["zero", "return_pct"],
                "adverse_return": scenarios.loc["adverse", "return_pct"],
                **{
                    p: parts.loc[p, "return_pct"]
                    for p in ("train", "validation", "test", "final_holdout")
                },
            }
        )
    return pd.DataFrame(rows)


def finish_batch(store, rows, preceding=None):
    table = pd.DataFrame(rows)
    table.to_csv(store.path / "results.csv", index=False)
    table.to_csv(store.path / "metrics.csv", index=False)
    comparison = classify(table)
    for column, ascending in (
        ("return_pct", False),
        ("sharpe", False),
        ("profit_factor", False),
        ("max_drawdown_pct", True),
    ):
        comparison["descriptive_rank_" + column] = comparison[column].rank(
            method="min", ascending=ascending, na_option="bottom"
        )
    comparison.to_csv(store.path / "comparison.csv", index=False)
    write_json(
        store.path / "classifications.json",
        clean_json(comparison[KEYS + ["classification"]].to_dict("records")),
    )
    wf = table[table.partition.str.startswith("wf_")]
    write_json(store.path / "walk_forward.json", clean_json(wf.to_dict("records")))
    cols = [
        "asset",
        "family",
        "architecture",
        "mode",
        "cohort",
        "return_pct",
        "sharpe",
        "sortino",
        "max_drawdown_pct",
        "profit_factor",
        "expectancy",
        "closed_trades",
        "time_in_market_pct",
        "total_costs",
        "classification",
    ]
    promising_count = int(comparison.classification.str.contains("PROMISING_BUT_UNCONFIRMED").sum())
    lines = [
        "# MTF research batch",
        "Frozen baseline/architecture experiment; no parameter tuning or automatic rank selection.",
        f"Executions: {len(table)}. Independent capital: {table.starting_equity.iloc[0]:.2f} USDT. "
        "USD-M perpetual, historical funding, inherited isolated-margin assumptions.",
        "Rules, exact costs, dataset identities and source snapshots are "
        "in plan/config/provenance. "
        "Stops: 2 ATR14 from the last CLOSED 1h candle; 72 elapsed hours. "
        "No new technical exit rules.",
        "## Full BASE comparison",
        markdown(comparison, cols),
        "## Temporal partitions (BASE)",
        markdown(
            table[
                (table.costs == "base")
                & table.partition.isin(["train", "validation", "test", "final_holdout"])
            ],
            KEYS + ["partition", "return_pct", "closed_trades", "max_drawdown_pct"],
        ),
        "## Continuous segments (BASE)",
        markdown(
            table[(table.costs == "base") & table.partition.str.startswith("segment_")],
            KEYS + ["partition", "start", "end", "return_pct", "closed_trades"],
        ),
        "## Stability and costs",
        markdown(
            comparison,
            KEYS
            + [
                "zero_return",
                "return_pct",
                "adverse_return",
                "wf_positive_fold_ratio",
                "final_holdout",
            ],
        ),
        "WF summaries use non-overlapping TEST windows only. The inherited"
        " 12-month training windows "
        "are recorded in the plan; no fitting or redundant training-window"
        " backtests are performed. "
        "Global TRAIN is evaluated separately. Segment accounts reset to "
        "initial capital; their returns "
        "must not be summed into a portfolio.",
        "## Interpretation",
        f"Positive full/base: {int((comparison.return_pct > 0).sum())}/{len(comparison)}. "
        f"Promising under inherited rules: {promising_count}. "
        "Ranks are descriptive. Sample sizes, costs, drawdown and holdout "
        "remain part of every decision. "
        "Previously observed markets are diagnostic history, not pristine OOS or paper trading.",
    ]
    if preceding is not None:
        joined = pd.concat([preceding, comparison], ignore_index=True)
        joined.to_csv(store.path / "baseline_comparison.csv", index=False)
        lines += ["## Previous phase reference", markdown(joined, cols)]
    (store.path / "summary.md").write_text("\n\n".join(lines) + "\n", encoding="utf-8")
    diagnostics = table[
        KEYS
        + [
            "partition",
            "costs",
            "SIGNALS_BASELINE",
            "SIGNALS_ACCEPTED_BY_4H",
            "SIGNALS_REJECTED_BY_4H",
            "filter_rejection_rate",
            "raw_signals_15m",
            "signals_after_1h_filter",
            "signals_after_4h_filter",
            "final_entries",
            "average_delay_to_entry",
            "delay_observations",
            "trades_per_month",
            "time_in_market_pct",
        ]
    ]
    diagnostics.to_csv(store.path / "signal_diagnostics.csv", index=False)
    (store.path / "diagnostics.md").write_text(
        "# Diagnostics\n\nSignals are decisions at close; fills use the next open. Closed 4h/1h "
        "features are backward-asof aligned by their availability, never by open time.\n\n"
        "All signal counts and acceptance rates are in signal_diagnostics.csv. Accepted/rejected "
        "6/24/72-hour raw-price returns are retained per execution in result.json. They are not "
        "counterfactual executed profits and overlapping signals are not independent.\n\n"
        "The delay field is elapsed time since a qualifying pullback touch for filled entries; "
        "it does not estimate a causal matched delay versus V1. Exposure is sampled at closes. "
        "The raw_signals_15m column refers to actual execution bars; see execution_bar_minutes.\n\n"
        "No missing candles/funding are invented. Positions close at segment boundaries, features "
        "reset and only cash carries between segments in a full account. Standalone segment "
        "accounts and chronological partitions are independent.\n\n"
        "V3/V4 use real quarter-hour execution bars via an invertible clock-unit adapter around "
        "the unchanged engine. Prices, quantities, funding rates and fees are not rescaled. "
        "The 72-hour stop is converted to 288 execution bars and reporting returns to UTC. "
        "Stop/liquidation resolution is therefore finer than V1/V2; attribution cannot treat "
        "all differences as a regime-filter effect. Historical margin tiers remain assumed.\n",
        encoding="utf-8",
    )
    return comparison


def finish_series(folder, comparisons, eligibility):
    table = pd.concat(comparisons, ignore_index=True)
    table.to_csv(folder / "master_table.csv", index=False)
    comparable = table[(table.cohort == "matched") & (table["mode"] == "LONG_ONLY")].copy()
    measures = [
        "return_pct",
        "sharpe",
        "max_drawdown_pct",
        "profit_factor",
        "expectancy",
        "win_rate_pct",
        "closed_trades",
        "total_costs",
        "time_in_market_pct",
        "SIGNALS_BASELINE",
        "SIGNALS_ACCEPTED_BY_4H",
        "filter_rejection_rate",
    ]
    comparable[measures] = comparable[measures].apply(pd.to_numeric)
    evolution = comparable.pivot(index=["asset", "family"], columns="architecture", values=measures)
    evolution.to_csv(folder / "mtf_evolution.csv")
    deltas = []
    for (asset, family), g in comparable.groupby(["asset", "family"]):
        g = g.set_index("architecture")
        for before, after in (("V1", "V2"), ("V2", "V3"), ("V3", "V4")):
            if before in g.index and after in g.index:
                deltas.append(
                    {
                        "asset": asset,
                        "family": family,
                        "change": before + " -> " + after,
                        **{m: g.loc[after, m] - g.loc[before, m] for m in measures},
                    }
                )
    pd.DataFrame(deltas).to_csv(folder / "mtf_deltas.csv", index=False)
    lines = [
        "# MTF EVOLUTION",
        "Original V1/V2 and the explicitly matched V1-V4 cohort are kept separate. "
        "Only matched rows support like-for-like period comparisons. No "
        "negative configurations are hidden.",
        markdown(
            table,
            [
                "asset",
                "family",
                "architecture",
                "mode",
                "cohort",
                "return_pct",
                "sharpe",
                "max_drawdown_pct",
                "profit_factor",
                "expectancy",
                "closed_trades",
                "total_costs",
                "classification",
            ],
        ),
        "## Changes on matched dates",
        markdown(pd.DataFrame(deltas), ["asset", "family", "change", *measures])
        if deltas
        else "No matched comparison available.",
        "A positive return delta alone does not establish improvement. Check risk, expectancy, "
        "sample size, costs and temporal classifications alongside it. V1->V2 isolates the "
        "4h regime gate; V2->V3 also changes the setup, trigger and execution clock; V3->V4 "
        "changes alignment to pullback/consolidation recovery. No pure filter attribution "
        "is made for those architectural changes. Rejection diagnostics are descriptive, "
        "and the pullback-delay field cannot prove whether MTF delays the same opportunity.",
        "## Eligibility for directional follow-up",
        json.dumps(eligibility, indent=2),
        "Eligibility copies the pre-existing PROMISING_BUT_UNCONFIRMED rules. Selection "
        "uses this already-observed diagnostic history; directional runs are not fresh OOS. "
        "No strategy is automatically approved for paper or live trading.",
    ]
    (folder / "summary.md").write_text("\n\n".join(lines) + "\n", encoding="utf-8")
