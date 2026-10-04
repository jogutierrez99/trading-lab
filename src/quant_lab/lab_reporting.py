"""Deterministic compact research artifacts. Ranking never uses holdout outcomes."""

import json
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

from quant_lab.experiments import write_json
from quant_lab.lab_schema import Experiment


def failure_reasons(row: dict, experiment: Experiment) -> list[str]:
    f = experiment.filters
    reasons = []
    checks = [
        ("closed_trades", f.minimum_trades, "min"),
        ("max_drawdown_pct", f.maximum_drawdown_pct, "max"),
        ("profit_factor", f.minimum_profit_factor, "min"),
        ("sharpe", f.minimum_sharpe, "min"),
    ]
    if row["status"] != "completed":
        return [row.get("error", "backtest_failed")]
    for name, threshold, operator in checks:
        if threshold is None:
            continue
        value = row.get(name)
        if value is None or (value < threshold if operator == "min" else value > threshold):
            reasons.append(f"{name}:{operator}={threshold}")
    if experiment.filters.positive_test and (
        row["period"] == "test"
        or row["period"].startswith("wf_")
        and row["period"].endswith("_test")
    ):
        if row["return_pct"] <= 0:
            reasons.append("nonpositive_test_return")
    if f.cost_stress_survival and row["scenario"] != "base" and row["return_pct"] <= 0:
        reasons.append("nonpositive_stress_return")
    return reasons


def reports(path: Path, experiment: Experiment, rows: list[dict], context: dict, code: dict):
    from quant_lab.lab_runner import rank_key

    for row in rows:
        row["filter_reasons"] = failure_reasons(row, experiment)
        row["filter_status"] = "FAIL" if row["filter_reasons"] else "PASS"
    serial = [
        r
        | {
            "parameters": json.dumps(r["parameters"], sort_keys=True),
            "costs": json.dumps(r["costs"], sort_keys=True),
            "filter_reasons": json.dumps(r["filter_reasons"]),
        }
        for r in rows
    ]
    pd.DataFrame(serial).to_csv(path / "metrics.csv", index=False, mode="x")
    leaderboard = []
    by_configuration = defaultdict(list)
    for row in rows:
        by_configuration[row["configuration_id"]].append(row)
    for train in sorted(
        (r for r in rows if r["period"] == "train" and r["scenario"] == "base"),
        key=lambda r: rank_key(r, experiment),
    ):
        matches = by_configuration[train["configuration_id"]]
        # Walk-forward winners form a separate adaptive procedure, not another full grid.
        fixed = [r for r in matches if r["period"] in {"train", "validation", "test"}]
        reasons = sorted(
            {
                f"{r['period']}/{r['scenario']}: {reason}"
                for r in fixed
                for reason in r["filter_reasons"]
            }
        )
        entry = {
            k: train[k]
            for k in (
                "configuration_id",
                "strategy",
                "strategy_version",
                "symbol",
                "timeframe",
                "mode",
            )
        }
        entry.update(
            parameters=json.dumps(train["parameters"], sort_keys=True),
            filter_status="FAIL" if reasons else "PASS",
            reason="; ".join(reasons),
        )
        for row in fixed:
            if row["scenario"] == "base":
                for metric in (
                    "return_pct",
                    "sharpe",
                    "max_drawdown_pct",
                    "profit_factor",
                    "closed_trades",
                    "expectancy",
                    "long_contribution",
                    "short_contribution",
                ):
                    entry[f"{row['period']}_{metric}"] = row.get(metric)
        leaderboard.append(entry)
    pd.DataFrame(leaderboard).to_csv(path / "leaderboard.csv", index=False, mode="x")
    passed = [r for r in leaderboard if r["filter_status"] == "PASS"]
    patterns = {}
    for key in context["parameters"][0]:
        frequencies = Counter(str(json.loads(r["parameters"])[key]) for r in passed)
        patterns[key] = {
            "most_common_20": dict(frequencies.most_common(20)),
            "distinct_values": len(frequencies),
            "other_configurations": sum(frequencies.values())
            - sum(count for _, count in frequencies.most_common(20)),
        }
    failures = Counter(reason for row in rows for reason in row["filter_reasons"])
    counts = {
        "total_backtests": len(rows),
        "valid_backtests": sum(r["status"] == "completed" for r in rows),
        "failed_backtests": sum(r["status"] != "completed" for r in rows),
        "filter_rejected_backtests": sum(r["filter_status"] == "FAIL" for r in rows),
        "survivors": len(passed),
        "configurations": len(leaderboard),
    }
    write_json(
        path / "summary.json",
        counts | {"failure_reasons": dict(failures), "parameter_patterns": patterns},
    )
    lines = [
        f"# {experiment.experiment_id}",
        "",
        f"Run ID: {path.name}",
        f"Strategy: {experiment.strategy.id} {context['template'].version}",
        f"Code hash: {code['code_sha256']}",
        f"Git commit: {code['git_revision']}",
        "Backend: StudyBackend v1; independent liquidated periods, causal warmup.",
        f"Execution: {experiment.execution.market_mode}; funding is not modelled.",
        "No automatic promising/validated designation or future-profit claim.",
        "",
        "## Datasets and periods",
        "",
    ]
    for dataset in context["datasets"]:
        lines.append(
            f"- {dataset['symbol']} {dataset['timeframe']}: {dataset['dataset_id']} "
            f"({dataset['start']} .. {dataset['end']}); SHA256 {dataset['parquet_sha256']}"
        )
    lines += [
        f"Modes: {', '.join(experiment.modes)}",
        "",
        "```json",
        json.dumps(experiment.validation.model_dump(mode="json"), indent=2),
        "```",
        "",
        "## Counts and predefined filters",
        "",
        "```json",
        json.dumps(counts | {"filters": experiment.filters.model_dump()}, indent=2),
        "```",
        "",
        "## Top configurations",
        "",
        f"Sorted ONLY by TRAIN/base {experiment.ranking.metric}, "
        f"{'descending' if experiment.ranking.descending else 'ascending'}; "
        "ties use configuration_id, undefined metrics last. Holdouts are descriptive.",
        "",
        "```json",
        json.dumps(leaderboard[: experiment.ranking.top_n], indent=2),
        "```",
        "",
        "## Walk-forward and cost stress",
        "",
        "Walk-forward selects each fold on TRAIN/base; only selected fold TEST rows "
        "are OOS results. Medians below are descriptive, not a compounded portfolio.",
        "",
    ]
    completed = pd.DataFrame([r for r in rows if r["status"] == "completed"])
    metrics = [
        "return_pct",
        "cagr_pct",
        "sharpe",
        "sortino",
        "max_drawdown_pct",
        "profit_factor",
        "win_rate_pct",
        "expectancy",
        "closed_trades",
        "average_close_exposure_pct",
        "fees_paid",
        "slippage_cost_closed_trades",
        "funding_pnl",
        "long_contribution",
        "short_contribution",
    ]
    if not completed.empty:
        completed[metrics] = completed[metrics].apply(pd.to_numeric).astype(float)
        grouped = completed.groupby(["period", "scenario"], sort=True)[metrics].median()
        lines += [
            "Median metrics across configurations (including TRAIN/validation/final TEST):",
            "",
            "```csv",
            grouped.to_csv().strip(),
            "```",
        ]
    lines += [
        "",
        "## Failure reasons",
        "",
        "```json",
        json.dumps(dict(failures), indent=2),
        "```",
        "",
        "## Parameter patterns among filter survivors",
        "",
        "```json",
        json.dumps(patterns, indent=2),
        "```",
        "",
        "## Files generated",
        "",
        "- experiment_snapshot.yaml: original YAML; relative references resolved in resolved.json",
        "- resolved.json: frozen strategy, defaults, parameters and dataset manifests",
        "- environment.json / provenance.json / plan.json: code/environment and experiment",
        "- ledger.sqlite: individual backtest lifecycle and result hashes",
        "- metrics.csv: all periods, costs, metrics and PASS/FAIL reasons",
        "- leaderboard.csv: configurations ranked on TRAIN/base with holdout columns",
        "- summary.json / summary.md / ai_summary.md: compact research summaries",
        "- run.json / outcome.json: immutable start and terminal records",
        "- <backtest_id>/result.json and equity.parquet: trades, rejections, metrics, equity",
        "",
        "Historical results do not establish future profitability.",
        "",
    ]
    text = "\n".join(lines)
    for name in ("summary.md", "ai_summary.md"):
        with (path / name).open("x", encoding="utf-8") as handle:
            handle.write(text)


def runs(root: Path) -> list[dict]:
    """Only two-level run metadata; never scan thousands of backtest artifacts."""
    result = []
    for path in (root / "results").glob("*/*/run.json"):
        meta = json.loads(path.read_text(encoding="utf-8"))
        if meta.get("kind") != "lab_experiment_v1":
            continue
        terminal = path.parent / "outcome.json"
        status = (
            json.loads(terminal.read_text(encoding="utf-8"))
            if terminal.exists()
            else {"status": "INCOMPLETE (running or interrupted)"}
        )
        result.append(meta | status | {"path": str(path.parent.resolve())})
    return sorted(result, key=lambda r: (r["created_at"], r["run_id"]))


def locate(root: Path, name: str) -> dict:
    found = [r for r in runs(root) if name == "latest" or r["experiment_id"] == name]
    if not found:
        raise ValueError(
            f"No lab runs for {name}; legacy reports remain in their original directories"
        )
    latest = found[-1]
    return latest | {
        filename: str(Path(latest["path"]) / filename)
        if (Path(latest["path"]) / filename).exists()
        else None
        for filename in ("ai_summary.md", "leaderboard.csv", "summary.md")
    }
