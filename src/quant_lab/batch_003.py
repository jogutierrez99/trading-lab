"""Frozen Batch 003 protocol. All history has already been observed."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_lab.batch import COSTS, Candidate, Window
from quant_lab.batch_002 import Batch002Plan
from quant_lab.batch_003_analysis import LABEL, monte_carlo, select_train
from quant_lab.batch_003_execution import Batch003Executor
from quant_lab.config import ResearchConfig, load_research_config, load_yaml
from quant_lab.execution_config import ExecutionConfig
from quant_lab.experiments import ExperimentStore, provenance, write_json
from quant_lab.history import HistoryRequest
from quant_lab.history_cache import fingerprint, read_bundle
from quant_lab.strategies.registry import StrategyRegistry


def verify_previous(repo):
    snapshot = json.loads((repo / "reports/batch_003/protected_previous.json").read_text())
    changed = [
        p
        for p, digest in snapshot.items()
        if hashlib.sha256((repo / p).read_bytes()).hexdigest() != digest
    ]
    if changed:
        raise ValueError(f"Previous batch files changed: {changed}")
    return {"protected_files": len(snapshot), "unchanged": True}


def frozen_references(repo):
    references = []
    for old in (
        "batch_001/20260921T204432Z-48a412b8930d",
        "batch_002/20260922T045248Z-daad23091510",
    ):
        folder = repo / "results" / old
        choices = json.loads((folder / "selection_train.json").read_text())
        metrics = pd.read_csv(folder / "metrics.csv")
        for name, choice in choices.items():
            rows = metrics[
                (metrics.candidate == choice["candidate"])
                & (metrics.costs == "base")
                & (metrics.partition == "train")
            ]
            source = folder / rows.iloc[0].experiment_id / "result.json"
            doc = json.loads(source.read_text())
            # JSON round-trip uses JSON mode for strict tuple models.
            research = ResearchConfig.model_validate_json(json.dumps(doc["research_config"]))
            references.append(
                (
                    Candidate(id="reference_" + choice["candidate"], strategy=name),
                    research,
                    {
                        "source": str(source.relative_to(repo)),
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    },
                )
            )
    return references


def run_batch003(config: Path, repo: Path):
    before = verify_previous(repo)
    plan = load_yaml(config, Batch002Plan)
    root = config.resolve().parent
    research = load_research_config(root / plan.app_file)
    execution = load_yaml(root / plan.execution_file, ExecutionConfig)
    if (
        execution.market_mode != "spot"
        or execution.direction != "long"
        or not execution.liquidate_at_end
    ):
        raise ValueError("Spot long with terminal liquidation required")
    if plan.warmup_bars < 1536 or plan.train.end > plan.folds[0].test.start:
        raise ValueError("Insufficient warmup or selection overlaps first WF test")
    parent = load_yaml(root / plan.history_file, HistoryRequest)
    candles = read_bundle(root / plan.dataset_dir, parent)
    legacy_parent = load_yaml(root / plan.legacy_history_file, HistoryRequest)
    legacy = read_bundle(root / plan.legacy_dataset_dir, legacy_parent)
    refs = frozen_references(repo)
    registry = StrategyRegistry().discover()
    code = provenance(repo)
    store = ExperimentStore(
        root / plan.output_dir,
        {
            "batch": "batch_003",
            "interpretation": LABEL,
            "plan": plan.model_dump(mode="json"),
            "research": research.model_dump(mode="json"),
            "execution": execution.model_dump(mode="json"),
            "costs": {k: v.model_dump() for k, v in COSTS.items()},
            "selection": (
                "TRAIN/base only: net>0, Sharpe>0, PF>1, trades>=40, DD<20. Within "
                "0.01 of maximum Sharpe: min DD, max PF, lexical ID. If none, baseline "
                "diagnostic only; insufficient if all variants <40 trades, else "
                "rejected."
            ),
            "classification": (
                "Primary label always REUSED_HISTORY_DIAGNOSTIC; never ROBUST. "
                "Diagnostic priority: failed train; insufficient final trades<30; "
                "failed after costs if zero positive/base nonpositive; FAILED_OOS if "
                "validation/test/final nonpositive; otherwise PROMISING_BUT_UNSTABLE. "
                "Adverse/WF recorded, cannot establish robustness on reused history."
            ),
            "regimes": (
                "Two axes: EMA50/200 with sideways absolute relative distance<=0.25%; "
                "ATR14/close vs preceding720 q30/q70. Unknown until ready. Not used in "
                "selection."
            ),
            "monte_carlo": (
                "Every new-strategy base-cost primary experiment with >=30 trades: "
                "10000 fixed cash-PnL permutations. Seed "
                "SHA256(candidate/partition/cost). Final return invariant; no "
                "bootstrap."
            ),
            "pullback_definition": (
                "Previous hourly low <= previous EMA; current close above EMA, RSI>50 "
                "and trend filter."
            ),
            "exposure": (
                "25% cap at entry including fee; no continuous rebalance. "
                "Mark-to-market exposure can exceed25%. Initial expected stop "
                "risk<=0.5%; gaps can exceed expected loss."
            ),
            "dataset": {
                label: {
                    "sha256": fingerprint(frame, request),
                    "first": str(frame.index[0]),
                    "last": str(frame.index[-1]),
                    "rows": len(frame),
                    "warmup": 1536,
                    "gaps": 0,
                    "scored_start": str(start),
                    "scored_rows": int((frame.index >= start).sum()),
                }
                for label, frame, request, start in (
                    ("primary", candles, parent, plan.train.start),
                    ("legacy", legacy, legacy_parent, pd.Timestamp("2022-02-03", tz="UTC")),
                )
            },
            "exclusions": (
                "March2023 gap and pre-June4 primary data excluded from scoring; "
                "context only. Legacy startsFeb3 2022. No cross-gap positions. No "
                "audited 2026 dataset available."
            ),
            "previous_references": [r[2] for r in refs],
            "protected_before": before,
            "verification_before": json.loads(
                (repo / "reports/batch_003/preflight.json").read_text()
            ),
        },
        code,
    )
    for folder in ("results", "equity", "trades", "charts", "mc_samples"):
        (store.path / folder).mkdir()
    executor = Batch003Executor(store, research, execution, registry)
    candidates = {c.id: c for c in plan.candidates}
    baselines = {c.strategy: c for c in plan.candidates if c.baseline}

    def run(c, window, part, cost="base", benchmark=None, old=False):
        return executor.execute(
            c,
            legacy if old else candles,
            legacy_parent if old else parent,
            window,
            part,
            cost,
            plan.warmup_bars,
            "legacy_observed" if old else "primary",
            benchmark,
        )

    trains = [run(c, plan.train, "train") for c in plan.candidates]
    selections = {
        n: select_train([r for r in trains if r["strategy"] == n], b.id)
        for n, b in baselines.items()
    }
    write_json(store.path / "selection_train.json", selections)
    for part in ("validation", "test"):
        for choice in selections.values():
            for cost in COSTS:
                run(candidates[choice["candidate"]], getattr(plan, part), part, cost)
    wf = []
    for i, fold in enumerate(plan.folds):
        for choice in selections.values():
            c = candidates[choice["candidate"]]
            run(c, fold.train, f"wf{i}_train")
            wf.append(run(c, fold.test, f"wf{i}_test"))
    wf_summary = {}
    for name in baselines:
        returns = np.array([r["return_pct"] for r in wf if r["strategy"] == name])
        wf_summary[name] = {
            "compounded_return_pct": float((np.prod(1 + returns / 100) - 1) * 100),
            "positive_folds_pct": float(np.mean(returns > 0) * 100),
            "median_return_pct": float(np.median(returns)),
            "worst_return_pct": float(returns.min()),
            "best_return_pct": float(returns.max()),
        }
    write_json(
        store.path / "walk_forward.json",
        {
            "interpretation": LABEL,
            "test_only": wf,
            "summary": wf_summary,
            "note": (
                "Fixed initial train selection; no fold re-selection. Independent "
                "accounts; test-only compounding. Overlaps static validation/test, not "
                "independent evidence."
            ),
        },
    )
    write_json(
        store.path / "holdout_unlocked.json",
        {
            "interpretation": LABEL,
            "selection": selections,
            "completed_experiments": len(executor.rows),
            "reason": (
                "Train, validation, test and frozen-variant WF completed before final "
                "reused partition"
            ),
        },
    )
    classifications = {}
    for name, choice in selections.items():
        scores = {
            cost: run(candidates[choice["candidate"]], plan.final_holdout, "final_holdout", cost)
            for cost in COSTS
        }
        diag = choice["diagnostic"]
        if choice["train_eligible"]:
            base, zero = scores["base"], scores["zero"]
            preceding = [
                r
                for r in executor.rows
                if r["strategy"] == name
                and r["partition"] in ("validation", "test")
                and r["costs"] == "base"
            ]
            diag = (
                "INSUFFICIENT_DATA"
                if base["closed_trades"] < 30
                else (
                    "FAILED_AFTER_COSTS"
                    if zero["return_pct"] > 0 >= base["return_pct"]
                    else "FAILED_OOS"
                    if min([base["return_pct"]] + [r["return_pct"] for r in preceding]) <= 0
                    else "PROMISING_BUT_UNSTABLE"
                )
            )
        classifications[name] = choice | {"classification": LABEL, "diagnostic": diag}
    full = Window(start=plan.train.start, end=plan.final_holdout.end)
    old_window = Window(
        start=pd.Timestamp("2022-02-03", tz="UTC").to_pydatetime(), end=legacy_parent.end
    )
    for baseline in baselines.values():
        run(baseline, full, "full_baseline_diagnostic")
        run(baseline, old_window, "legacy_baseline_diagnostic", old=True)
    first = next(iter(baselines.values()))
    for part in ("train", "validation", "test", "final_holdout"):
        for cost in COSTS:
            for pct in (25.0, 100.0):
                run(first, getattr(plan, part), f"benchmark_{part}", cost, pct)
    for pct in (25.0, 100.0):
        run(first, full, "benchmark_full_baseline_diagnostic", benchmark=pct)
        run(first, old_window, "benchmark_legacy_diagnostic", benchmark=pct, old=True)
    for candidate, frozen, _ in refs:
        reference_executor = Batch003Executor(store, frozen, execution, registry)
        for window, part in ((full, "reference_full"), (plan.final_holdout, "reference_final")):
            reference_executor.execute(
                candidate, candles, parent, window, part, "base", plan.warmup_bars
            )
        executor.rows.extend(reference_executor.rows)
    write_json(store.path / "classifications.json", classifications)
    pd.DataFrame(executor.rows).to_csv(store.path / "metrics.csv", index=False)
    mc, regime = {}, {}
    for row in executor.rows:
        ident = row["experiment_id"]
        doc = json.loads((store.path / ident / "result.json").read_text())
        regime[ident] = {
            "candidate": row["candidate"],
            "partition": row["partition"],
            "costs": row["costs"],
            "benchmark_pct": row["benchmark_pct"],
            "report": doc["regimes"],
        }
        if (
            row["costs"] == "base"
            and row["benchmark_pct"] is None
            and row["candidate"] in candidates
            and row["dataset_label"] == "primary"
        ):
            report, samples = monte_carlo(
                [t["net_pnl"] for t in doc["trades"]], f"{row['candidate']}/{row['partition']}/base"
            )
            mc[ident] = {
                "candidate": row["candidate"],
                "partition": row["partition"],
                "interpretation": LABEL,
            } | report
            if samples is not None:
                np.save(store.path / "mc_samples" / f"{ident}.npy", samples)
    write_json(store.path / "monte_carlo.json", mc)
    write_json(store.path / "regime_analysis.json", regime)
    with store.connect() as db:
        ledger = db.execute("SELECT id,status,result_sha256 FROM experiments").fetchall()
    assert all(
        status == "completed"
        and hashlib.sha256((store.path / ident / "result.json").read_bytes()).hexdigest() == digest
        for ident, status, digest in ledger
    )
    assert provenance(repo)["code_sha256"] == code["code_sha256"]
    write_json(
        store.path / "verification.json",
        {
            "interpretation": LABEL,
            "preflight": json.loads((repo / "reports/batch_003/preflight.json").read_text()),
            "protected_after": verify_previous(repo),
            "frozen_code_unchanged": True,
            "completed": len(ledger),
            "ledger_hashes_valid": True,
            "per_run_fill_risk_cap_cost_equity_assertions": True,
        },
    )
    return store.path
