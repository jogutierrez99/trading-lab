"""Read compact lab artifacts and write a new immutable descriptive comparison."""

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd

from quant_lab.experiments import write_json
from quant_lab.lab_classification import latest_classification
from quant_lab.lab_evidence import completed_run
from quant_lab.lab_reporting import locate


def compare(root: Path, experiments: list[str]) -> Path:
    if len(experiments) < 2 or len(set(experiments)) != len(experiments):
        raise ValueError("Compare requires at least two distinct experiment IDs")
    sources, rows, best = [], [], []
    for name in experiments:
        run = locate(root, name)
        if run["status"] != "COMPLETE":
            raise ValueError(f"{name}: latest run is not COMPLETE")
        path = Path(run["path"])
        plan = json.loads((path / "plan.json").read_text(encoding="utf-8"))
        resolved = json.loads((path / "resolved.json").read_text(encoding="utf-8"))
        metrics = pd.read_csv(path / "metrics.csv")
        leaderboard = pd.read_csv(path / "leaderboard.csv")
        evidence = completed_run(root, run["run_id"])
        supplemental = latest_classification(root, evidence)
        classification = None
        if supplemental:
            class_path, document = supplemental
            classification = {
                "counts": document["counts"],
                "policy_id": document["policy"]["policy_id"],
                "policy_sha256": document["policy_sha256"],
                "path": str(class_path),
                "sha256": hashlib.sha256(class_path.read_bytes()).hexdigest(),
            }
        sources.append(
            {
                "experiment": name,
                "run_id": run["run_id"],
                "research_classification": classification,
                "path": str(path),
                "validation": plan["validation"],
                "filters": plan["filters"],
                "strategy": plan["strategy"],
                "costs": resolved["app"]["costs"],
                "execution": resolved["execution"],
                "datasets": [
                    {k: d[k] for k in ("symbol", "timeframe", "dataset_id", "parquet_sha256")}
                    for d in resolved["datasets"]
                ],
                "sha256": {
                    file: hashlib.sha256((path / file).read_bytes()).hexdigest()
                    for file in ("plan.json", "resolved.json", "metrics.csv", "leaderboard.csv")
                },
            }
        )
        # Leaderboard already orders TRAIN/base only. Never reorder by holdout.
        best.append(
            {
                "experiment": name,
                "train_ranked_examples": json.loads(
                    leaderboard.head(plan["ranking"]["top_n"]).to_json(orient="records")
                ),
            }
        )
        parameter_count = len(resolved["parameters"])
        variants = sorted({str(p.get("variant", "unspecified")) for p in resolved["parameters"]})
        for (period, scenario, mode), group in metrics.groupby(
            ["period", "scenario", "mode"], sort=True
        ):
            valid = group.loc[group.status == "completed"]
            row = {
                "experiment": name,
                "variants": ",".join(variants),
                "parameter_configurations": parameter_count,
                "configurations_all_markets_modes": len(leaderboard),
                "valid_configurations_all_periods": len(leaderboard),
                "classifications_all_periods": json.dumps(dict(Counter(leaderboard.filter_status))),
                "period": period,
                "scenario": scenario,
                "mode": mode,
                "configurations": group.configuration_id.nunique(),
                "valid_configurations": valid.configuration_id.nunique(),
                "PASS": int((group.filter_status == "PASS").sum()),
                "FAIL": int((group.filter_status == "FAIL").sum()),
                "legacy_PASS": int((group.filter_status == "PASS").sum()),
                "legacy_FAIL": int((group.filter_status == "FAIL").sum()),
                "research_classification_counts_all_periods": json.dumps(
                    classification["counts"], sort_keys=True
                )
                if classification
                else None,
            }
            for metric in ("return_pct", "max_drawdown_pct", "sharpe", "expectancy"):
                values = pd.to_numeric(valid[metric], errors="coerce").dropna()
                row["median_" + metric] = float(values.median()) if len(values) else None
            rows.append(row)
    directory = (
        root
        / "reports/lab-comparison"
        / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12])
    )
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "sources.json", sources)
    write_json(directory / "comparison.json", rows)
    write_json(directory / "train_ranked_examples.json", best)
    pd.DataFrame(rows).to_csv(directory / "comparison.csv", index=False, mode="x")
    text = (
        "# Lab comparison\n\nDescriptive medians; independent markets/modes, not a portfolio.\n"
        "PASS/FAIL columns retain only legacy filters; they are not research or paper eligibility. "
        "New classifications are shown only when a hash-matched classification supplement exists. "
        "Counts describe whole configurations, not each period row; do not sum repeated counts. "
        "See sources.json for policy IDs/hashes; different policies are not interchangeable.\n"
        "TEST is the final holdout; no separate FINAL exists. "
        "No profitability or paper eligibility claim.\n"
        "Compare sources.json for periods, datasets, costs and execution assumptions.\n\n"
        + "\n".join(f"- {s['experiment']}: {s['run_id']}" for s in sources)
        + "\n\n## Comparison by period, cost scenario and direction\n\n```csv\n"
        + pd.DataFrame(rows).to_csv(index=False)
        + "```\n\n"
        "TRAIN-only descriptive examples: train_ranked_examples.json. Source results unchanged.\n"
    )
    for name in ("summary.md", "ai_summary.md"):
        (directory / name).write_text(text, encoding="utf-8")
    write_json(
        directory / "outcome.json",
        {
            "status": "COMPLETE",
            "sha256": {
                name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                for name in (
                    "sources.json",
                    "comparison.json",
                    "comparison.csv",
                    "train_ranked_examples.json",
                    "summary.md",
                    "ai_summary.md",
                )
            },
        },
    )
    return directory
