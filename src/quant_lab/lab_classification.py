"""Staged research evidence. Stage one receives TRAIN/VALIDATION rows only."""

import hashlib
import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

import pandas as pd

from quant_lab.config import load_yaml
from quant_lab.experiments import write_json
from quant_lab.lab_classification_policy import ClassificationPolicy, MetricGate
from quant_lab.lab_evidence import (
    assert_unchanged,
    completed_run,
    new_id,
    portable,
    read_json,
    recorded_data_valid,
    sha256,
)

STATES = ("FAIL", "VALID", "RESEARCH_PASS", "OOS_PASS", "ROBUST_PASS", "PAPER_TRADING_CANDIDATE")
PRINCIPAL = (
    "closed_trades",
    "return_pct",
    "profit_factor",
    "sharpe",
    "expectancy",
    "max_drawdown_pct",
)


def finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def technical(row: dict | None) -> list[str]:
    if row is None:
        return ["missing_row"]
    reasons = []
    if row.get("status") != "completed":
        reasons.append("not_completed")
    reasons += [f"undefined:{key}" for key in PRINCIPAL if not finite(row.get(key))]
    trades = row.get("closed_trades")
    if finite(trades) and (trades < 1 or trades != int(trades)):
        reasons.append("insufficient_or_invalid_trades")
    for key in ("profit_factor", "max_drawdown_pct"):
        if finite(row.get(key)) and row[key] < 0:
            reasons.append(f"negative:{key}")
    if row.get("error"):
        reasons.append("internal_error")
    return reasons


def gate(row: dict | None, rule: MetricGate) -> list[str]:
    reasons = technical(row)
    if reasons:
        return reasons
    checks = {
        "closed_trades": (rule.minimum_trades, False),
        "profit_factor": (rule.minimum_profit_factor, False),
        "sharpe": (rule.minimum_sharpe, False),
        "expectancy": (rule.minimum_expectancy, rule.expectancy_strict),
        "return_pct": (rule.minimum_return_pct, rule.return_strict),
    }
    for key, (minimum, strict) in checks.items():
        if minimum is not None and (row[key] <= minimum if strict else row[key] < minimum):
            reasons.append(f"{key}:{'>' if strict else '>='}{minimum}")
    if row["max_drawdown_pct"] > rule.maximum_drawdown_pct:
        reasons.append(f"max_drawdown_pct:<={rule.maximum_drawdown_pct}")
    return reasons


def index_rows(rows: list[dict]) -> dict:
    result = {}
    for row in rows:
        key = row["period"], row["scenario"]
        if key in result:
            raise ValueError("Duplicate period/scenario for one configuration")
        result[key] = row
    return result


def research_stage(rows: list[dict], policy: ClassificationPolicy, data_valid: bool) -> dict:
    # Explicit projection is also enforced at the public boundary. TEST/WF fields
    # cannot participate in this stage, even if supplied accidentally by a caller.
    cells = index_rows([r for r in rows if r["period"] in {"train", "validation"}])
    tech = [] if data_valid else ["data_or_warmup_provenance_unverified"]
    economic = []
    for period in ("train", "validation"):
        for scenario in ("base", policy.adverse_scenario):
            row = cells.get((period, scenario))
            if scenario == "base" or row is not None:
                tech += [f"{period}/{scenario}:{x}" for x in technical(row)]
    economic += [
        f"train/{policy.adverse_scenario}:{x}"
        for x in technical(cells.get(("train", policy.adverse_scenario)))
    ]
    for period, scenario, rule in (
        ("train", "base", policy.train),
        ("validation", "base", policy.validation),
        ("validation", policy.adverse_scenario, policy.validation_adverse),
    ):
        economic += [f"{period}/{scenario}:{x}" for x in gate(cells.get((period, scenario)), rule)]
    return {
        "VALID": not tech,
        "RESEARCH_PASS": not tech and not economic,
        "technical_reasons": tech,
        "research_reasons": economic,
    }


def wf_stage(rows: list[dict], policy: ClassificationPolicy, folds: list[dict]) -> dict:
    cells = index_rows(
        [r for r in rows if r["period"].startswith("wf_") and r["period"].endswith("_test")]
    )
    base, adverse, reasons, details = [], [], [], {}
    if len(folds) != policy.robustness.required_folds:
        reasons.append("required_fold_count")
    for i, fold in enumerate(folds):
        label = f"wf_{i}_test"
        details[label] = {}
        for scenario, target in (("base", base), (policy.adverse_scenario, adverse)):
            row = cells.get((label, scenario))
            errors = technical(row)
            if row is not None and any(
                pd.Timestamp(row[k]) != pd.Timestamp(fold["test"][k]) for k in ("start", "end")
            ):
                errors.append("fold_dates_mismatch")
            if errors:
                reasons += [f"{label}/{scenario}:{e}" for e in errors]
            else:
                target.append(row)
            details[label][scenario] = {
                "technical_valid": not errors,
                "reasons": errors,
                "return_positive": bool(
                    row is not None and finite(row.get("return_pct")) and row["return_pct"] > 0
                ),
                "expectancy_nonnegative": bool(
                    row is not None and finite(row.get("expectancy")) and row["expectancy"] >= 0
                ),
                "backtest_id": row.get("backtest_id") if row else None,
            }
    g = policy.robustness
    if reasons:
        return {
            "pass": False,
            "reasons": reasons,
            "folds_available": len(base),
            "wf_tests": details,
        }
    returns = [r["return_pct"] for r in base]
    expectations = [r["expectancy"] for r in base]
    positive = sum(x > 0 for x in returns)
    nonnegative = sum(x >= 0 for x in expectations)
    stressed = sum(r["return_pct"] > 0 for r in adverse)
    for ok, reason in (
        (positive >= g.positive_return_folds, "positive_return_folds"),
        (nonnegative >= g.nonnegative_expectancy_folds, "nonnegative_expectancy_folds"),
        (median(returns) > 0, "median_return_not_positive"),
        (median(expectations) > 0, "median_expectancy_not_positive"),
        (stressed >= g.positive_adverse_folds, "positive_adverse_folds"),
    ):
        if not ok:
            reasons.append(reason)
    return {
        "pass": not reasons,
        "reasons": reasons,
        "positive_folds": positive,
        "nonnegative_expectancy_folds": nonnegative,
        "positive_adverse_folds": stressed,
        "median_return_pct": median(returns),
        "median_expectancy": median(expectations),
        "wf_tests": details,
    }


def oos_count(rows: list[dict]) -> dict:
    # BASE only. Prefer disjoint selected WF tests, then final TEST; only add
    # VALIDATION if wholly disjoint. Never count the same interval twice.
    selected = [
        r
        for r in rows
        if r["scenario"] == "base"
        and (
            r["period"] in {"test", "validation"}
            or (r["period"].startswith("wf_") and r["period"].endswith("_test"))
        )
    ]
    selected.sort(key=lambda r: (r["period"] == "validation", r["start"], r["period"]))
    intervals, included, excluded = [], [], []
    total = 0
    for row in selected:
        start, end = pd.Timestamp(row["start"]), pd.Timestamp(row["end"])
        if technical(row) or end <= start or any(start < b and end > a for a, b in intervals):
            excluded.append(row["period"])
            continue
        intervals.append((start, end))
        included.append(row["period"])
        total += int(row["closed_trades"])
    return {"trades": total, "included_base_periods": included, "excluded_periods": excluded}


def classify_configuration(
    rows: list[dict], policy: ClassificationPolicy, folds: list[dict], data_valid: bool = False
) -> dict:
    stage = research_stage(rows, policy, data_valid)
    cells = index_rows(rows)
    frozen = sorted(
        (r for r in rows if r["period"] in {"train", "validation"}), key=lambda r: r["backtest_id"]
    )
    stage["research_evidence_sha256"] = hashlib.sha256(json.dumps(frozen).encode()).hexdigest()
    stage["OOS_PASS"] = stage["ROBUST_PASS"] = stage["PAPER_TRADING_CANDIDATE"] = False
    stage["oos_reasons"] = ["not_evaluated_before_research_pass"]
    stage["robustness"] = {"pass": False, "reasons": ["not_evaluated_before_oos_pass"]}
    stage["oos_evidence"] = {"trades": 0, "included_base_periods": [], "excluded_periods": []}
    if stage["RESEARCH_PASS"]:
        stage["oos_reasons"] = [
            f"test/{scenario}:{reason}"
            for scenario, rule in (
                ("base", policy.test),
                (policy.adverse_scenario, policy.test_adverse),
            )
            for reason in gate(cells.get(("test", scenario)), rule)
        ]
        stage["OOS_PASS"] = not stage["oos_reasons"]
    if stage["OOS_PASS"]:
        stage["robustness"] = wf_stage(rows, policy, folds)
        stage["robustness"]["evidence_scope"] = "fixed_candidate_robustness"
        stage["ROBUST_PASS"] = stage["robustness"]["pass"]
    if stage["ROBUST_PASS"]:
        stage["oos_evidence"] = oos_count(rows)
        stage["PAPER_TRADING_CANDIDATE"] = (
            stage["oos_evidence"]["trades"] >= policy.minimum_total_oos_trades
        )
    stage["research_classification"] = next((s for s in reversed(STATES[1:]) if stage[s]), "FAIL")
    stage["paper_reasons"] = (
        []
        if stage["PAPER_TRADING_CANDIDATE"]
        else [f"minimum_total_oos_trades:{policy.minimum_total_oos_trades}"]
        if stage["ROBUST_PASS"]
        else ["requires_all_prior_gates"]
    )
    return stage


def classify_evidence(evidence: dict, policy: ClassificationPolicy, fixed_rows=None) -> dict:
    if evidence["header"]["kind"] != "lab_experiment_v1":
        raise ValueError(
            "HISTORICAL_CHALLENGE has no TRAIN/VALIDATION/TEST; research gates not applicable"
        )
    frame = evidence["metrics"]
    folds = evidence["plan"]["validation"]["walk_forward"]
    # Technical provenance for stage one deliberately excludes TEST and WF rows.
    pretest = evidence | {"metrics": frame[frame.period.isin(["train", "validation"])]}
    data_valid = recorded_data_valid(pretest)
    candidates = []
    candidate_frame = frame
    if fixed_rows is not None:
        from quant_lab.lab_robustness import merge_fixed

        candidate_frame = merge_fixed(evidence, fixed_rows)
    for identity, group in candidate_frame.groupby("configuration_id", sort=True):
        rows = json.loads(group.to_json(orient="records"))
        first = rows[0]
        result = classify_configuration(rows, policy, folds, data_valid)
        candidates.append(
            {
                "configuration_id": identity,
                "symbol": first["symbol"],
                "timeframe": first["timeframe"],
                "mode": first["mode"],
                "parameters": json.loads(first["parameters"]),
                **result,
            }
        )
    adaptive = []
    wf = frame[frame.period.str.match(r"^wf_\d+_test$")]
    for (symbol, timeframe, mode), group in wf.groupby(["symbol", "timeframe", "mode"], sort=True):
        adaptive.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "mode": mode,
                "scope": "selected_adaptive_procedure_only_not_fixed_candidate",
                "selected_configuration_ids": sorted(group.configuration_id.unique().tolist()),
                **wf_stage(json.loads(group.to_json(orient="records")), policy, folds),
            }
        )
    counts = {
        state: sum(c["research_classification"] == state for c in candidates) for state in STATES
    }
    return {
        "classification_schema_version": 1,
        "policy": policy.model_dump(mode="json"),
        "created_at": datetime.now(UTC).isoformat(),
        "experiment": evidence["header"]["experiment_id"],
        "run_id": evidence["header"]["run_id"],
        "source_sha256": evidence["source_sha256"],
        "counts": counts,
        "candidates": candidates,
        "adaptive_wf": adaptive,
        "walk_forward_selection": adaptive,
        "fixed_candidate_robustness": {c["configuration_id"]: c["robustness"] for c in candidates},
        "legacy_filter_counts": dict(Counter(frame.get("filter_status", []))),
        "scope": "Retrospective diagnostic; recorded dataset/warmup provenance checked, "
        "no new dataset/equity/trade audit. No proof of independent unobserved holdout. "
        "PAPER_TRADING_CANDIDATE is a protocol label, never order/forward authorization.",
    }


def classification_text(document: dict) -> str:
    lines = [
        f"# Research classification: {document['experiment']}",
        "",
        f"Run: {document['run_id']}",
        "",
        document["scope"],
        "",
        "Legacy PASS is only the old filter result; it is not a research or paper gate.",
        "Research gate reads TRAIN/VALIDATION only. TEST never ranks candidates.",
        "fixed_candidate_robustness requires all prescribed WF TESTs for that same candidate.",
        "walk_forward_selection reports adaptive winners separately; "
        "their evidence is not pooled into each candidate.",
        "OOS trades count BASE disjoint WF TESTs + TEST, and VALIDATION only if nonoverlapping.",
        "Medians across independently reset folds are descriptive, not compounded returns.",
        "",
        "## Mutually exclusive highest classification",
        "",
        "```json",
        json.dumps(document["counts"], indent=2),
        "```",
        "",
        "Per-candidate gates, per-fold technical validity, return/expectancy flags and "
        "failure reasons: classification.json.",
        "Historical results do not establish future profitability.",
        "",
    ]
    return "\n".join(lines)


def classify(root: Path, identifier: str, policy_path: Path | None = None) -> Path:
    policy_path = policy_path or root / "configs/research/lab_classification_v1.yaml"
    policy = load_yaml(policy_path, ClassificationPolicy)
    evidence = completed_run(root, identifier)
    from quant_lab.lab_robustness import latest_robustness

    fixed = latest_robustness(root, evidence)
    document = classify_evidence(evidence, policy, fixed[2] if fixed else None)
    if fixed:
        document["fixed_robustness_source"] = portable(fixed[0], root)
        document["fixed_robustness_sha256"] = sha256(fixed[0])
    document["policy_sha256"] = sha256(policy_path)
    document["implementation_sha256"] = {
        name: sha256(Path(__file__).with_name(name))
        for name in ("lab_classification.py", "lab_classification_policy.py", "lab_evidence.py")
    }
    document["source"] = portable(evidence["path"], root)
    assert_unchanged(evidence)
    directory = root / "reports/lab-classification" / evidence["header"]["run_id"] / new_id()
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "classification.json", document)
    text = classification_text(document)
    for name in ("classification.md", "summary.md", "ai_summary.md"):
        with (directory / name).open("x", encoding="utf-8") as handle:
            handle.write(text)
    return directory


def latest_classification(root: Path, evidence: dict) -> tuple[Path, dict] | None:
    paths = list(
        (root / "reports/lab-classification" / evidence["header"]["run_id"]).glob(
            "*/classification.json"
        )
    )
    if not paths:
        return None
    pairs = [(p, read_json(p)) for p in paths]
    path, document = max(pairs, key=lambda item: (item[1]["created_at"], item[0].parent.name))
    if document["source_sha256"] != evidence["source_sha256"]:
        raise ValueError("Stale classification: source hashes changed; classify again")
    if document.get("fixed_robustness_source"):
        from quant_lab.lab_robustness import latest_robustness

        fixed = latest_robustness(root, evidence)
        if (
            fixed is None
            or portable(fixed[0], root) != document["fixed_robustness_source"]
            or sha256(fixed[0]) != document["fixed_robustness_sha256"]
        ):
            raise ValueError("Stale classification: robustness supplement changed; classify again")
    return path, document
