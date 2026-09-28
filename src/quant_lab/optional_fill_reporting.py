"""Deterministic paired reporting; causal fallback losses remain visible."""

import json

import pandas as pd

from quant_lab.cross_market_study import clean_json
from quant_lab.entry_timing_reporting import finite, markdown

KEYS = ["asset", "family", "architecture", "partition", "costs"]
CRITERIA = {
    "numeric_tolerance": 1e-8,
    "retention_warning": 0.98,
    "retention_failure": 0.95,
    "material_relative_expectancy_pf": 0.05,
    "material_return_pp": 2.0,
    "material_holdout_return_pp": 2.0,
    "cost_allowance_relative": 0.01,
    "cost_allowance_minimum_usdt": 1.0,
    "adverse_improved_limit_pp": 2.0,
    "adverse_worse_limit_pp": 5.0,
    "positive_fold_improved_loss": 1,
    "positive_fold_worse_loss": 2,
    "fallback": "Current market open, possibly worse; never backdated.",
    "worse_fill_rule": (
        "All worse fills prevent IMPROVED; only worse optimized fills are invariant errors."
    ),
}


def classify(b, o, bh, oh, ba, oa, bf, of):
    def known(*values):
        return all(finite(v) for v in values)

    worse = {
        "retention_below_95": finite(o.get("trade_retention_rate"))
        and o["trade_retention_rate"] < 0.95,
        "worse_optimized_fill": o["number_of_worse_optimized_fills"] > 0,
        "positive_fold_loss_gt_2": bf - of > 2,
        "material_return_loss": o["return_pct"] < b["return_pct"] - 2,
        "material_holdout_return_loss": oh["return_pct"] < bh["return_pct"] - 2,
        "adverse_loss_gt_5pp": oa["return_pct"] < ba["return_pct"] - 5,
    }
    for name in ("expectancy", "profit_factor"):
        if known(b.get(name), o.get(name)):
            worse["material_" + name + "_loss"] = o[name] < b[name] - 0.05 * abs(b[name]) - 1e-8
    if known(bh.get("expectancy"), oh.get("expectancy")):
        worse["material_holdout_expectancy_loss"] = (
            oh["expectancy"] < bh["expectancy"] - 0.05 * abs(bh["expectancy"]) - 1e-8
        )
    improved = {
        "retention_at_least_98": finite(o.get("trade_retention_rate"))
        and o["trade_retention_rate"] >= 0.98,
        "no_worse_fills_including_fallback": o["number_of_worse_fills"] == 0,
        "expectancy_preserved": known(b.get("expectancy"), o.get("expectancy"))
        and o["expectancy"] >= b["expectancy"],
        "pf_preserved": known(b.get("profit_factor"), o.get("profit_factor"))
        and o["profit_factor"] >= b["profit_factor"],
        "return_preserved": o["return_pct"] >= b["return_pct"],
        "drawdown_preserved": o["max_drawdown_pct"] <= b["max_drawdown_pct"] + 1e-8,
        "costs_not_materially_worse": o["total_costs"]
        <= b["total_costs"] + max(1.0, 0.01 * abs(b["total_costs"])),
        "holdout_expectancy_not_materially_worse": known(bh.get("expectancy"), oh.get("expectancy"))
        and oh["expectancy"] >= bh["expectancy"] - 0.05 * abs(bh["expectancy"]) - 1e-8,
        "positive_fold_loss_at_most_1": bf - of <= 1,
        "adverse_loss_at_most_2pp": oa["return_pct"] >= ba["return_pct"] - 2,
        "observed_improvement": (
            finite(o.get("average_fill_improvement_pct"))
            and o["average_fill_improvement_pct"] > 1e-8
        )
        or o["return_pct"] > b["return_pct"] + 1e-8,
    }
    failures = [k for k, v in worse.items() if v]
    label = (
        "FILL_WORSE" if failures else "FILL_IMPROVED" if all(improved.values()) else "FILL_NEUTRAL"
    )
    reasons = failures or (
        ["all_improvement_conditions_met"]
        if label == "FILL_IMPROVED"
        else [k for k, v in improved.items() if not v]
    )
    return {
        "classification": label,
        "reasons": "; ".join(reasons),
        "improvement_checks": json.dumps(improved, sort_keys=True),
        "worse_checks": json.dumps(worse, sort_keys=True),
        "next_candidate": {
            "FILL_WORSE": "ARCHIVE_FILL_VARIANT",
            "FILL_IMPROVED": "CONTINUE_FILL_RESEARCH",
            "FILL_NEUTRAL": "NO_MEANINGFUL_IMPROVEMENT",
        }[label],
    }


def report(folder, rows, reproduction, plan, failed):
    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame(columns=KEYS + ["variant"])
    base, opt = (frame.loc[frame.variant == v] for v in ("baseline", "optimized"))
    paired = base.merge(opt, on=KEYS, suffixes=("_baseline", "_optimized"), validate="one_to_one")
    classifications = []
    for c in plan["config"]["configurations"]:
        key = (c["asset"], c["family"], c["architecture"])
        identity = {k: c[k] for k in ("asset", "family", "architecture")}
        if key in failed:
            classifications.append(
                identity
                | {
                    "classification": "FILL_WORSE",
                    "reasons": failed[key],
                    "next_candidate": "ARCHIVE_FILL_VARIANT",
                }
            )
            continue
        sub = frame.loc[
            (frame.asset == key[0]) & (frame.family == key[1]) & (frame.architecture == key[2])
        ]

        def row(v, partition="full", costs="base", sub=sub):
            selected = sub.loc[
                (sub.variant == v) & (sub.partition == partition) & (sub.costs == costs)
            ]
            if len(selected) != 1:
                raise ValueError("Incomplete unique paired observation")
            return selected.iloc[0].to_dict()

        b, o = row("baseline"), row("optimized")
        bh, oh = row("baseline", "final_holdout"), row("optimized", "final_holdout")
        ba, oa = row("baseline", costs="adverse"), row("optimized", costs="adverse")
        folds = sub.loc[sub.partition.str.startswith("wf_") & (sub.costs == "base")]
        if any(len(folds.loc[folds.variant == v]) != 22 for v in ("baseline", "optimized")):
            raise ValueError("All 22 folds required")
        bf, of = [
            int(((folds.variant == v) & (folds.return_pct > 0)).sum())
            for v in ("baseline", "optimized")
        ]
        result = identity | classify(b, o, bh, oh, ba, oa, bf, of)
        for short, name in (
            ("return", "return_pct"),
            ("dd", "max_drawdown_pct"),
            ("pf", "profit_factor"),
            ("expectancy", "expectancy"),
            ("trades", "closed_trades"),
            ("costs", "total_costs"),
        ):
            result["baseline_" + short], result["optimized_" + short] = b[name], o[name]
            result[short + "_delta"] = (
                o[name] - b[name] if finite(o[name]) and finite(b[name]) else None
            )
        for name in ("return_pct", "profit_factor", "expectancy"):
            result["baseline_holdout_" + name], result["optimized_holdout_" + name] = (
                bh[name],
                oh[name],
            )
        for name in ("return_pct", "profit_factor"):
            result["baseline_adverse_" + name], result["optimized_adverse_" + name] = (
                ba[name],
                oa[name],
            )
        result.update(baseline_positive_folds=bf, optimized_positive_folds=of)
        for name in (
            "optimization_rate",
            "fallback_rate",
            "optimized_entries",
            "fallback_entries",
            "unexecuted_entries",
            "trade_retention_rate",
            "retention_warning",
            "unexecuted_reasons",
            "average_wait_minutes",
            "median_wait_minutes",
            "average_fill_improvement_pct",
            "median_fill_improvement_pct",
            "average_fill_improvement_atr",
            "median_fill_improvement_atr",
            "number_of_worse_fills",
            "number_of_worse_optimized_fills",
            "number_of_worse_fallback_fills",
        ):
            result[name] = o[name]
        classifications.append(result)
    classified = pd.DataFrame(classifications)
    subsets = {
        "results": frame,
        "metrics": frame,
        "paired_comparison": paired,
        "baseline_reproduction": pd.DataFrame(reproduction),
        "fill_classification": classified,
        "fill_metrics": frame[
            [
                c
                for c in frame
                if c in KEYS + ["variant"]
                or c.startswith(
                    (
                        "signals_",
                        "optimized_",
                        "fallback_",
                        "optimization_",
                        "trade_retention",
                        "retention_",
                        "average_fill",
                        "median_fill",
                        "average_wait",
                        "median_wait",
                        "number_of_worse",
                        "unexecuted_",
                    )
                )
            ]
        ],
        "fold_metrics": frame.loc[frame.partition.str.startswith("wf_")],
        "segment_metrics": frame.loc[frame.partition.str.startswith("segment_")],
        "holdout": frame.loc[frame.partition == "final_holdout"],
        "cost_sensitivity": frame.loc[frame.partition == "full"],
    }
    for name, table in subsets.items():
        table.to_csv(folder / (name + ".csv"), index=False, mode="x")
    limits = (
        "Causal deadline-market fallback was explicitly selected by the user. It can fill worse "
        "than the baseline; it never restores a historical price/time after observing the future. "
        "number_of_worse_fills includes fallback losses; optimized replacements must strictly "
        "improve price. Position occupancy and sizing can reduce retention; every missing trade is "
        "explained in trade_pairs.csv. Baseline hourly versus experimental quarter execution may "
        "change stops, liquidation timing, funding and holding duration; PnL changes cannot be "
        "attributed only to entry price. Capital and sizing use unchanged rules. ZERO disables "
        "funding, BASE/ADVERSE retain it. Holdout has already been observed: this is exploratory "
        "research, not pristine validation. Overlapping windows are not independent samples."
    )
    main_columns = [
        "asset",
        "family",
        "architecture",
        "baseline_return",
        "optimized_return",
        "baseline_dd",
        "optimized_dd",
        "baseline_pf",
        "optimized_pf",
        "baseline_expectancy",
        "optimized_expectancy",
        "baseline_trades",
        "optimized_trades",
        "optimization_rate",
        "average_fill_improvement_pct",
        "classification",
    ]
    temporal = [c for c in classified if "holdout" in c or "adverse" in c or "folds" in c]
    behaviour = [
        c
        for c in classified
        if c.startswith(
            (
                "optimized_entries",
                "fallback_entries",
                "optimization_rate",
                "fallback_rate",
                "trade_retention",
                "average_",
                "median_",
                "number_of_worse",
                "unexecuted_",
            )
        )
    ]
    ai = [
        "# Optional 15m Fill Optimizer — AI Summary",
        "## Executive summary",
        f"Run: {folder.name}. Backtests completed: {len(frame)} / {plan['expected_executions']}. "
        f"Code: {plan['code_sha256']}. Six configured pairs; failed baseline pairs: {len(failed)}. "
        "Frozen BTC/ETH matched cohort, 18 exclusions; data hashes in plan.json. "
        "Reproduction statuses in baseline_reproduction.csv. Generated locally without AI calls.",
        "## Main results",
        markdown(classified.reindex(columns=main_columns)),
        "## Per configuration",
    ]
    for result in classifications:
        ai += [
            f"### {result['asset']} {result['family']} {result['architecture']}",
            markdown(
                pd.DataFrame([result]).drop(
                    columns=["improvement_checks", "worse_checks"], errors="ignore"
                )
            ),
        ]
    ai += [
        "## Execution behaviour",
        markdown(classified[["asset", "family", "architecture"] + behaviour]),
        "## Temporal robustness",
        markdown(classified[["asset", "family", "architecture"] + temporal]),
        "## Classification reasons",
        markdown(
            classified.reindex(
                columns=[
                    "asset",
                    "family",
                    "architecture",
                    "classification",
                    "reasons",
                    "improvement_checks",
                    "worse_checks",
                ]
            )
        ),
        "## Research interpretation",
        limits,
        "## Next candidates",
        markdown(classified[["asset", "family", "architecture", "next_candidate"]]),
    ]
    (folder / "ai_summary.md").write_text("\n\n".join(ai) + "\n", encoding="utf-8")
    technical = [
        "# Optional 15m Fill — Technical Summary",
        "## Protocol and configurations",
        "```json\n" + json.dumps(clean_json(plan), indent=2, default=str) + "\n```",
    ]
    for name, table in subsets.items():
        technical += ["## " + name.replace("_", " "), markdown(table)]
    technical += [
        "## Trade retention and mapping",
        "trade_pairs.csv includes every baseline entry, even when not executed. Missing trades "
        "have explicit reasons; warning below 98%, mandatory explanation below 95%.",
        "## Limitations",
        limits,
    ]
    (folder / "summary.md").write_text("\n\n".join(technical) + "\n", encoding="utf-8")
    return classified
