"""Fixed paired criteria and local, evidence-only Markdown templates."""

import json
import math

import pandas as pd

from quant_lab.cross_market_study import clean_json
from quant_lab.entry_timing_execution import CASES

KEYS = ["asset", "family", "architecture", "partition", "costs"]
CRITERIA = {
    "improved": {
        "relative_return_loss": 0.10,
        "minimum_trades": 50,
        "adverse_loss_pp": 5,
        "positive_fold_loss": 2,
    },
    "worse": {
        "minimum_trades": 30,
        "low_execution_rate": 0.10,
        "material_holdout_return_loss_pp": 5,
        "material_holdout_expectancy_loss_relative": 0.20,
        "material_adverse_loss_pp": 10,
        "positive_fold_loss": 4,
    },
    "trade_retention_warning": 0.30,
    "precedence": "WORSE, then all IMPROVED conditions, otherwise MIXED",
}


def finite(value):
    return value is not None and math.isfinite(float(value))


def classify(b, t, bh, th, ba, ta, bf, tf):
    required = [
        b.get(k)
        for k in (
            "return_pct",
            "max_drawdown_pct",
            "profit_factor",
            "expectancy",
            "closed_trades",
            "total_costs",
        )
    ]
    required += [
        t.get(k)
        for k in (
            "return_pct",
            "max_drawdown_pct",
            "profit_factor",
            "expectancy",
            "closed_trades",
            "total_costs",
            "signal_execution_rate",
        )
    ]
    required += [
        bh.get("expectancy"),
        th.get("expectancy"),
        bh.get("return_pct"),
        th.get("return_pct"),
        ba.get("return_pct"),
        ta.get("return_pct"),
    ]
    # Undefined statistics cannot count as successful evidence. Still report known failures.
    worse = {}
    if finite(t.get("profit_factor")):
        worse["profit_factor_below_1"] = t["profit_factor"] < 1
    worse["nonpositive_full_return"] = t["return_pct"] <= 0
    worse["fewer_than_30_trades"] = t["closed_trades"] < 30
    worse["positive_folds_drop_gt_4"] = bf - tf > 4
    if finite(b.get("expectancy")) and finite(t.get("expectancy")):
        worse["expectancy_lost"] = b["expectancy"] > 0 >= t["expectancy"]
    worse["material_adverse_deterioration"] = ta["return_pct"] < ba["return_pct"] - 10
    worse["material_holdout_return_deterioration"] = th["return_pct"] < bh["return_pct"] - 5
    if finite(bh.get("expectancy")) and finite(th.get("expectancy")):
        worse["material_holdout_expectancy_deterioration"] = th["expectancy"] < bh[
            "expectancy"
        ] - 0.20 * abs(bh["expectancy"])
    if all(
        finite(value)
        for value in (
            b.get("expectancy"),
            b.get("profit_factor"),
            t.get("expectancy"),
            t.get("profit_factor"),
            t.get("signal_execution_rate"),
        )
    ):
        quality = t["expectancy"] > b["expectancy"] and t["profit_factor"] >= b["profit_factor"]
        worse["low_execution_without_quality"] = t["signal_execution_rate"] < 0.10 and not quality
    complete = all(finite(v) for v in required)
    improved = {}
    if complete:
        improved = {
            "expectancy_improved": t["expectancy"] > b["expectancy"],
            "profit_factor_preserved": t["profit_factor"] >= b["profit_factor"],
            "drawdown_preserved": t["max_drawdown_pct"] <= b["max_drawdown_pct"],
            "relative_return_floor": t["return_pct"]
            >= b["return_pct"] - 0.10 * abs(b["return_pct"]),
            "costs_preserved": t["total_costs"] <= b["total_costs"],
            "at_least_50_trades": t["closed_trades"] >= 50,
            "holdout_expectancy_preserved": th["expectancy"] >= bh["expectancy"],
            "adverse_within_5pp": ta["return_pct"] >= ba["return_pct"] - 5,
            "positive_folds_within_2": bf - tf <= 2,
        }
    failures = [k for k, v in worse.items() if v]
    classification = (
        "TIMING_WORSE"
        if failures
        else "TIMING_IMPROVED"
        if complete and all(improved.values())
        else "TIMING_MIXED"
    )
    retention = t["closed_trades"] / b["closed_trades"] if b["closed_trades"] else None
    reasons = failures if failures else [k for k, v in improved.items() if not v]
    if not complete:
        reasons.append("insufficient_or_undefined_metrics")
    if classification == "TIMING_IMPROVED":
        reasons = ["all_nine_improvement_conditions_met"]
    return {
        "classification": classification,
        "reasons": "; ".join(reasons),
        "improvement_checks": json.dumps(improved, sort_keys=True),
        "worse_checks": json.dumps(worse, sort_keys=True),
        "trade_retention_rate": retention,
        "sample_warning": retention is not None and retention < 0.30,
        "next_research_candidate": "ARCHIVE_TIMING_VARIANT"
        if classification == "TIMING_WORSE"
        else "CONTINUE_RESEARCH"
        if classification == "TIMING_IMPROVED"
        else "NEED_MORE_DATA",
        "baseline_positive_folds": bf,
        "timing_positive_folds": tf,
        "baseline_holdout_expectancy": bh.get("expectancy"),
        "timing_holdout_expectancy": th.get("expectancy"),
        "baseline_holdout_return": bh["return_pct"],
        "timing_holdout_return": th["return_pct"],
        "baseline_adverse_return": ba["return_pct"],
        "timing_adverse_return": ta["return_pct"],
    }


def markdown(frame):
    def cell(value):
        if value is None or isinstance(value, float) and math.isnan(value):
            return "N/A"
        return (
            str(round(value, 6) if isinstance(value, float) else value)
            .replace("|", "/")
            .replace("\n", " ")
        )

    return (
        "| "
        + " | ".join(frame.columns)
        + " |\n| "
        + " | ".join("---" for _ in frame.columns)
        + " |\n"
        + "\n".join(
            "| " + " | ".join(map(cell, r)) + " |" for r in frame.itertuples(index=False, name=None)
        )
    )


def finish(folder, rows, plan, replay):
    frame = pd.DataFrame(rows)
    if frame.duplicated(KEYS + ["variant"]).any():
        raise ValueError("Duplicate paired observation")
    base, timing = (frame.loc[frame.variant == v] for v in ("baseline", "timing"))
    paired = base.merge(timing, on=KEYS, suffixes=("_baseline", "_timing"), validate="one_to_one")
    if len(paired) * 2 != len(frame):
        raise ValueError("Missing paired observations")
    classifications = []
    for asset, family, architecture in CASES:
        subset = frame.loc[
            (frame.asset == asset) & (frame.family == family) & (frame.architecture == architecture)
        ]

        def row(v, partition="full", costs="base", subset=subset):
            values = subset.loc[
                (subset.variant == v) & (subset.partition == partition) & (subset.costs == costs)
            ]
            if len(values) != 1:
                raise ValueError("Missing unique classification observation")
            return values.iloc[0].to_dict()

        folds = subset.loc[subset.partition.str.startswith("wf_") & (subset.costs == "base")]
        if any(len(folds.loc[folds.variant == v]) != 22 for v in ("baseline", "timing")):
            raise ValueError("Classification requires all 22 folds")
        positive = [
            int(((folds.variant == v) & (folds.return_pct > 0)).sum())
            for v in ("baseline", "timing")
        ]
        b, t = row("baseline"), row("timing")
        result = classify(
            b,
            t,
            row("baseline", "final_holdout"),
            row("timing", "final_holdout"),
            row("baseline", costs="adverse"),
            row("timing", costs="adverse"),
            *positive,
        )
        main = {"asset": asset, "family": family, "architecture": architecture}
        for short, key in (
            ("return", "return_pct"),
            ("dd", "max_drawdown_pct"),
            ("pf", "profit_factor"),
            ("expectancy", "expectancy"),
            ("trades", "closed_trades"),
            ("costs", "total_costs"),
        ):
            main["baseline_" + short], main["timing_" + short] = b[key], t[key]
        classifications.append(main | result)
    classified = pd.DataFrame(classifications)
    subsets = {
        "results": frame,
        "metrics": frame,
        "paired_comparison": paired,
        "segment_metrics": frame.loc[frame.partition.str.startswith("segment_")],
        "fold_metrics": frame.loc[frame.partition.str.startswith("wf_")],
        "holdout": frame.loc[frame.partition == "final_holdout"],
        "cost_sensitivity": frame.loc[frame.partition == "full"],
        "timing_metrics": frame[
            KEYS
            + ["variant"]
            + [
                c
                for c in frame
                if c.startswith(
                    (
                        "signals_",
                        "signal_execution",
                        "average_wait",
                        "median_wait",
                        "average_entry",
                        "median_entry",
                        "average_fill",
                        "median_fill",
                        "paired_fills",
                        "trade_retention_rate",
                        "sample_warning",
                    )
                )
            ]
        ],
        "timing_classification": classified,
    }
    for name, table in subsets.items():
        table.to_csv(folder / (name + ".csv"), index=False, mode="x")
    full = frame.loc[(frame.partition == "full") & (frame.costs == "base")]
    timing_columns = [
        "family",
        "architecture",
        "signals_created",
        "signals_entered",
        "signals_expired",
        "signals_invalidated",
        "signals_blocked_extension",
        "signal_execution_rate",
        "average_wait_minutes",
        "median_wait_minutes",
        "average_entry_distance_atr",
        "median_entry_distance_atr",
        "average_fill_improvement_pct",
        "median_fill_improvement_pct",
        "paired_fills",
    ]
    temporal_columns = [
        "family",
        "architecture",
        "baseline_positive_folds",
        "timing_positive_folds",
        "baseline_holdout_return",
        "timing_holdout_return",
        "baseline_holdout_expectancy",
        "timing_holdout_expectancy",
        "baseline_adverse_return",
        "timing_adverse_return",
    ]
    limitation = (
        "Research only; these configurations were selected using previously observed results, "
        "including holdout, so this is not a new pristine holdout. Same risk/cost/margin/funding "
        "model; timing executes protective orders on quarter bars whereas baseline retains its "
        "original hourly execution resolution. This resolution difference is part of the study "
        "and prevents attributing every PnL change solely to entry price. Signal-reference ATR is "
        "frozen; 72 elapsed hours remain unchanged. Windows overlap: never sum their trades or "
        "PnL as independent evidence. Missing paired fills remain missing, never imputed. "
        "ZERO disables execution costs and funding exactly as the original protocol."
    )
    ai = [
        "# Entry Timing 15m — AI Summary",
        "## Executive summary",
        f"Backtests: {len(frame)} ({len(base)} reproduced baseline + {len(timing)} timing). "
        f"Three ETHUSDT pairs / six variants. Baseline reproduction: {len(replay)} verified. "
        f"Code: `{plan['code_sha256']}`. Data: frozen matched cohort, 18 excluded days; "
        "identities in plan.json. No network/model calls.",
        "## Main results",
        markdown(classified.iloc[:, :16]),
    ]
    for title, result in zip(("Supertrend V2", "ROC V2", "ROC V1"), classifications, strict=True):
        ai += [
            "## " + title,
            markdown(pd.DataFrame([result]).drop(columns=["improvement_checks", "worse_checks"])),
        ]
    ai += [
        "## Timing behaviour",
        markdown(full.loc[full.variant == "timing", timing_columns]),
        markdown(classified[["family", "architecture", "trade_retention_rate", "sample_warning"]]),
        "## Temporal robustness",
        markdown(classified[temporal_columns]),
        "## Classification reasons",
        markdown(
            classified[
                [
                    "family",
                    "architecture",
                    "classification",
                    "reasons",
                    "improvement_checks",
                    "worse_checks",
                ]
            ]
        ),
        "## Research interpretation",
        "Classification follows frozen comparisons only. Lower drawdown with a smaller sample "
        "does not establish improved edge. " + limitation,
        "## Next research candidates",
        markdown(classified[["family", "architecture", "next_research_candidate"]]),
    ]
    (folder / "ai_summary.md").write_text("\n\n".join(ai) + "\n", encoding="utf-8")
    technical = [
        "# Entry Timing 15m — Technical Summary",
        "## Protocol and configuration",
        "```json\n" + json.dumps(clean_json(plan), indent=2, default=str) + "\n```",
        "## Baseline reproduction",
        f"All {len(replay)} baselines reproduced before any timing execution; "
        "numerical rtol=1e-9, atol=1e-8. Full trace in baseline_reproduction.json.",
        "## Complete results",
        markdown(frame),
        "## Paired comparison",
        markdown(paired),
        "## Temporal validation",
        "Identical frozen windows, exclusions and independent capital per execution. "
        "Historical warmup is causal and resets at gaps.",
        "## Holdout",
        markdown(subsets["holdout"]),
        "## Folds",
        markdown(subsets["fold_metrics"]),
        "## Segments",
        markdown(subsets["segment_metrics"]),
        "## Costs and funding",
        markdown(subsets["cost_sensitivity"]),
        "## Timing metrics and signal lifecycle",
        markdown(subsets["timing_metrics"]),
        "signals.csv and signal_lifecycle.csv contain every original opportunity, transitions "
        "and reasons. trades.csv links each entry to exactly one signal_id within window/scenario.",
        "## Final classification",
        markdown(classified),
        "## Limitations",
        limitation,
    ]
    (folder / "summary.md").write_text("\n\n".join(technical) + "\n", encoding="utf-8")
    return classified
