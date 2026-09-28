"""Deterministic watchlist enrichment; never grants execution eligibility."""

import json
import math

import pandas as pd

from quant_lab.study_report import markdown

MINIMUMS = {
    "full_return": ("gt", 0),
    "full_expectancy": ("gt", 0),
    "full_sharpe": ("gt", 0),
    "full_pf": ("ge", 1.03),
    "full_drawdown": ("le", 25),
    "full_trades": ("ge", 75),
    "adverse_return": ("gt", -20),
    "adverse_pf": ("ge", 0.80),
    "holdout_trades": ("ge", 15),
    "positive_folds": ("ge", 7),
}
RULES = {
    "full_return_gt": ("full_return", "full_return_pass", "profitability"),
    "full_pf_ge": ("full_pf", "full_pf_pass", "profitability"),
    "full_expectancy_gt": ("full_expectancy", "full_expectancy_pass", "profitability"),
    "full_sharpe_gt": ("full_sharpe", "full_sharpe_pass", "profitability"),
    "full_drawdown_le": ("full_drawdown", "full_drawdown_pass", "drawdown"),
    "full_trades_ge": ("full_trades", "full_trades_pass", "sample size"),
    "holdout_trades_ge": ("holdout_trades", "holdout_trades_pass", "sample size"),
    "holdout_return_ge": ("holdout_return", "holdout_return_pass", "holdout"),
    "holdout_expectancy_gt": ("holdout_expectancy", "holdout_expectancy_pass", "holdout"),
    "holdout_pf_ge": ("holdout_pf", "holdout_pf_pass", "holdout"),
    "positive_folds_ge": ("positive_folds", "folds_pass", "temporal stability"),
    "adverse_return_gt": ("adverse_return", "adverse_return_pass", "costs"),
    "adverse_pf_ge": ("adverse_pf", "adverse_pf_pass", "costs"),
}
ALIASES = {
    "return_pct": "full_return",
    "profit_factor": "full_pf",
    "sharpe": "full_sharpe",
    "expectancy": "full_expectancy",
    "max_drawdown_pct": "full_drawdown",
    "closed_trades": "full_trades",
}


def finite(value):
    return value is not None and pd.notna(value) and math.isfinite(float(value))


def enrich(table: pd.DataFrame, thresholds: dict) -> pd.DataFrame:
    records = []
    for row in table.to_dict("records"):
        row.update({target: row[source] for source, target in ALIASES.items()})
        checks = json.loads(row["criteria_checks"])
        failed = [name for name in RULES if not checks[name]]
        minimum = {}
        for name, (op, threshold) in MINIMUMS.items():
            value = row[name]
            minimum[name] = bool(
                finite(value)
                and (
                    value > threshold
                    if op == "gt"
                    else value >= threshold
                    if op == "ge"
                    else value <= threshold
                )
            )
        # Completeness is an integrity gate, not a fourteenth economic criterion.
        valid = checks["complete_folds"] and all(finite(row[spec[0]]) for spec in RULES.values())
        near = not row["research_pass"] and valid and all(minimum.values()) and len(failed) <= 2
        label = (
            "RESEARCH_PASS" if row["research_pass"] else "NEAR_PASS" if near else "RESEARCH_FAIL"
        )
        critical = [name for name, passed in minimum.items() if not passed]
        if row["research_pass"]:
            reason = "All frozen RESEARCH_PASS criteria satisfied."
        elif not valid:
            reason = "Invalid or incomplete metrics/folds; watchlist classification disallowed."
        elif critical:
            reason = "Failed critical minimum criteria: " + ", ".join(critical) + "."
        elif near:
            reason = (
                f"Passed minimum research viability rules; failed {len(failed)}/13 "
                "RESEARCH_PASS criteria: " + ", ".join(failed) + "."
            )
        else:
            reason = f"Failed {len(failed)}/13 RESEARCH_PASS criteria; maximum allowed is 2."
        distances = {}
        for name, (metric, column, _category) in RULES.items():
            row[column] = checks[name]
            value, threshold = row[metric], thresholds[name]
            distances[name] = {
                "value": float(value) if finite(value) else None,
                "threshold": threshold,
                "operator": name.rsplit("_", 1)[1],
                "value_minus_threshold": float(value - threshold) if finite(value) else None,
            }
        row.update(
            {
                "research_classification": label,
                "failed_pass_criteria": ";".join(failed),
                "failed_pass_criteria_count": len(failed),
                "classification_reason": reason,
                "minimum_criteria_checks": json.dumps(minimum, sort_keys=True),
                "pass_threshold_distances": json.dumps(distances, sort_keys=True),
                "issue_categories": ";".join(sorted({RULES[name][2] for name in failed})),
                "metrics_complete": bool(valid),
            }
        )
        row.update({"minimum_" + k + "_pass": v for k, v in minimum.items()})
        records.append(row)
    if not records:
        return table.copy()
    return (
        pd.DataFrame(records)
        .sort_values(["asset", "family", "architecture"])
        .reset_index(drop=True)
    )


def watchlist_summary(classified: pd.DataFrame) -> str:
    near = classified[classified.research_classification == "NEAR_PASS"]
    lines = [
        "## NEAR_PASS WATCHLIST",
        "Watchlist only. NEAR_PASS does not authorize V4, paper or live trading.",
    ]
    columns = [
        "asset",
        "family",
        "architecture",
        "full_return",
        "full_pf",
        "full_sharpe",
        "full_drawdown",
        "full_expectancy",
        "holdout_return",
        "holdout_trades",
        "positive_folds",
        "adverse_return",
        "failed_pass_criteria",
    ]
    lines.append(markdown(near, columns) if len(near) else "No NEAR_PASS configurations.")
    for row in near.to_dict("records"):
        checks = json.loads(row["criteria_checks"])
        lines.append(f"### {row['asset']} / {row['family']} / {row['architecture']}")
        lines.append("PASS criteria satisfied: " + ", ".join(k for k in RULES if checks[k]))
        lines.append(row["classification_reason"])
        lines.append("Issue categories (no subjective priority): " + row["issue_categories"])
        distances = json.loads(row["pass_threshold_distances"])
        for name in RULES:
            if not checks[name]:
                d = distances[name]
                lines.append(
                    f"- {name}: value={d['value']:.8g}; requires {d['operator']} "
                    f"{d['threshold']}; value minus threshold="
                    f"{d['value_minus_threshold']:.8g}. "
                    "A strict gt threshold requires exceeding, not equaling, the limit."
                )
    return "\n\n".join(lines) + "\n"


def write_classification(folder, classified):
    classified.to_csv(folder / "research_classification.csv", index=False, mode="x")
    classified[classified.research_classification == "NEAR_PASS"].to_csv(
        folder / "near_pass.csv", index=False, mode="x"
    )
    return watchlist_summary(classified)
