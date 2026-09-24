"""Batch 002: explicit rolling folds and a final holdout opened only after test."""

from pathlib import Path

import pandas as pd
from pydantic import Field, model_validator

from quant_lab.batch import COSTS, Candidate, Window, classify, resolve_candidate, select_candidate
from quant_lab.batch_execution import BatchExecutor, report_table
from quant_lab.config import StrictModel, load_research_config, load_yaml
from quant_lab.execution_config import ExecutionConfig
from quant_lab.experiments import ExperimentStore, provenance, write_json
from quant_lab.history import HistoryRequest
from quant_lab.history_cache import fingerprint, read_bundle
from quant_lab.strategies.registry import StrategyRegistry


class Fold(StrictModel):
    train: Window
    test: Window

    @model_validator(mode="after")
    def check(self):
        if self.train.end != self.test.start:
            raise ValueError("Fold train must end at test start")
        if pd.Timestamp(self.train.start) + pd.DateOffset(months=12) != self.train.end:
            raise ValueError("Fold training must span 12 calendar months")
        if pd.Timestamp(self.test.start) + pd.DateOffset(months=3) != self.test.end:
            raise ValueError("Fold test must span 3 calendar months")
        return self


class Batch002Plan(StrictModel):
    app_file: str
    execution_file: str
    history_file: str
    dataset_dir: str
    legacy_history_file: str
    legacy_dataset_dir: str
    output_dir: str
    warmup_bars: int = Field(default=768, ge=764, le=10000)
    train: Window
    validation: Window
    test: Window
    final_holdout: Window
    folds: list[Fold] = Field(min_length=1)
    candidates: list[Candidate] = Field(min_length=12, max_length=12)

    @model_validator(mode="after")
    def check(self):
        windows = [self.train, self.validation, self.test, self.final_holdout]
        if any(left.end != right.start for left, right in zip(windows, windows[1:], strict=False)):
            raise ValueError("Static partitions must be ordered and adjacent")
        if len({c.id for c in self.candidates}) != len(self.candidates):
            raise ValueError("Duplicate candidate IDs")
        names = {c.strategy for c in self.candidates}
        if len(names) != 4:
            raise ValueError("Batch 002 requires four strategy families")
        for name in names:
            group = [c for c in self.candidates if c.strategy == name]
            if len(group) != 3 or sum(c.baseline for c in group) != 1:
                raise ValueError("Each family needs three variants and one baseline")
        previous = None
        for fold in self.folds:
            if fold.train.start < self.train.start or fold.test.end > self.final_holdout.start:
                raise ValueError("Fold cannot cross final holdout or predate study")
            if previous is not None and fold.test.start != previous:
                raise ValueError("Walk-forward tests must be adjacent, with no overlap")
            previous = fold.test.end
        return self


def run_batch002(config: Path, repo_root: Path) -> Path:
    plan = load_yaml(config, Batch002Plan)
    root = config.resolve().parent
    research = load_research_config(root / plan.app_file)
    execution = load_yaml(root / plan.execution_file, ExecutionConfig)
    if (
        execution.market_mode != "spot"
        or execution.direction != "long"
        or not execution.liquidate_at_end
    ):
        raise ValueError("Batch 002 requires spot long only and terminal liquidation")
    parent = load_yaml(root / plan.history_file, HistoryRequest)
    candles = read_bundle(root / plan.dataset_dir, parent)
    legacy_request = load_yaml(root / plan.legacy_history_file, HistoryRequest)
    legacy = read_bundle(root / plan.legacy_dataset_dir, legacy_request)
    if legacy_request.end > parent.download_start:
        raise ValueError("Legacy diagnostic must be independent of primary study")
    if plan.train.start != parent.start or plan.final_holdout.end != parent.end:
        raise ValueError("Static plan must cover the complete primary study")
    registry = StrategyRegistry().discover()
    for candidate in plan.candidates:
        registry.create(resolve_candidate(research, candidate).strategies[0])
    store = ExperimentStore(
        root / plan.output_dir,
        {
            "batch": "batch_002",
            "plan": plan.model_dump(mode="json"),
            "research": research.model_dump(mode="json"),
            "execution": execution.model_dump(mode="json"),
            "primary_dataset_id": fingerprint(candles, parent),
            "legacy_dataset_id": fingerprint(legacy, legacy_request),
            "costs": {name: cost.model_dump() for name, cost in COSTS.items()},
            "selection": "train base only: >=20 trades, return>0, DD<=25; "
            "max Sharpe/min turnover/ID",
            "exposure_policy": "Sizing at entry only; cap 25% including fee at entry, "
            "no rebalancing",
            "interpretation": "New hypotheses after viewing Batch001. "
            "No independent claim on legacy.",
            "robust_label_enabled": False,
        },
        provenance(repo_root),
    )
    executor = BatchExecutor(store, research, execution, registry)
    baselines = {c.strategy: c for c in plan.candidates if c.baseline}
    candidates = {c.id: c for c in plan.candidates}

    def run(candidate, window, partition, costs="base", benchmark=None, old=False):
        return executor.execute(
            candidate,
            legacy if old else candles,
            legacy_request if old else parent,
            window,
            partition,
            costs,
            plan.warmup_bars,
            "legacy_observed" if old else "primary",
            benchmark,
        )

    def select(window, label):
        rows = [run(c, window, label) for c in plan.candidates]
        selected = {}
        for name, baseline in baselines.items():
            group = [dict(row, partition="train") for row in rows if row["strategy"] == name]
            chosen, eligible = select_candidate(group, baseline.id)
            selected[name] = {"candidate": chosen, "train_eligible": eligible}
        write_json(store.path / f"selection_{label}.json", selected)
        return selected

    selections = select(plan.train, "train")
    for partition in ("validation", "test"):
        for choice in selections.values():
            for costs in COSTS:
                run(candidates[choice["candidate"]], getattr(plan, partition), partition, costs)
    # Complete rolling research before opening the final holdout. Never reselect static candidates.
    wf = []
    for i, fold in enumerate(plan.folds):
        selected = select(fold.train, f"wf{i}_train")
        for choice in selected.values():
            wf.append(run(candidates[choice["candidate"]], fold.test, f"wf{i}_test"))
    write_json(
        store.path / "walk_forward.json",
        {
            "test_only": wf,
            "compounded_test_return_pct": {
                name: float(
                    (
                        pd.Series(
                            [1 + r["return_pct"] / 100 for r in wf if r["strategy"] == name]
                        ).prod()
                        - 1
                    )
                    * 100
                )
                for name in baselines
            },
            "note": "12m rolling train, 3m tests, independent capital per fold. Overlaps static "
            "validation/test; not independent evidence. No final holdout data used.",
        },
    )
    write_json(
        store.path / "holdout_unlocked.json",
        {
            "selection": selections,
            "completed_experiments": len(executor.rows),
            "reason": "Train, validation, test and walk-forward complete; "
            "fixed selections unchanged.",
        },
    )
    classifications = {}
    for name, choice in selections.items():
        scores = {
            cost: run(candidates[choice["candidate"]], plan.final_holdout, "final_holdout", cost)
            for cost in COSTS
        }
        classifications[name] = classify(scores["base"], scores["zero"]) | choice
        classifications[name]["adverse_return_pct"] = scores["adverse"]["return_pct"]
    full = Window(start=plan.train.start, end=plan.final_holdout.end)
    old_window = Window(start=legacy_request.start, end=legacy_request.end)
    for baseline in baselines.values():
        run(baseline, full, "full_baseline_diagnostic")
        run(baseline, old_window, "legacy_baseline_diagnostic", old=True)
    first = next(iter(baselines.values()))
    for part in ("train", "validation", "test", "final_holdout"):
        for costs in COSTS:
            for pct in (25.0, 100.0):
                run(first, getattr(plan, part), f"benchmark_{part}", costs, pct)
    for pct in (25.0, 100.0):
        run(first, full, "benchmark_full_baseline_diagnostic", benchmark=pct)
        run(first, old_window, "benchmark_legacy_diagnostic", benchmark=pct, old=True)
    write_json(store.path / "classifications.json", classifications)
    pd.DataFrame(executor.rows).to_csv(store.path / "metrics.csv", index=False)
    lines = [
        "# Batch 002 — BTC/USDT spot 1h, solo largos",
        "",
        "10.000 USDT por cuenta independiente. Sin cartera conjunta ni apalancamiento.",
        "Costes base/adversos iguales a Batch 001. Todos los rangos son UTC, fin exclusivo.",
        "",
    ]
    for name in ("train", "validation", "test", "final_holdout"):
        window = getattr(plan, name)
        lines.append(f"- {name}: {window.start.date()} a {window.end.date()}.")
    lines += [
        "",
        "La variante base se usa como diagnóstico si ninguna pasa train.",
        "Squeeze compara contra 720 anchos anteriores; la compresión debe preceder la ruptura.",
        "Momentum incluye close actual y filtro EMA; no es una comparación aislada del sizing.",
        "Exposición recalculada solo al entrar; 25% es límite al entrar, no rebalanceo continuo.",
        "",
    ]
    for part in (
        "train",
        "validation",
        "test",
        "final_holdout",
        "full_baseline_diagnostic",
        "legacy_baseline_diagnostic",
    ):
        lines += (
            [f"## {part}", ""]
            + report_table(
                [
                    r
                    for r in executor.rows
                    if r["partition"] == part and (r["costs"] == "base" or part == "final_holdout")
                ]
            )
            + [""]
        )
    lines += ["## Clasificación del holdout final", ""]
    for name, value in classifications.items():
        lines.append(f"- {name}: {value}.")
    lines += [
        "",
        "El tramo legacy se solapa con datos ya observados; es solo diagnóstico.",
        "Walk-forward agrega solo tests; se solapa con validation/test estáticos.",
        "No se atraviesa marzo 2023, no se agregan ambos tramos como una equity continua.",
        "Ninguna etiqueta ROBUST. Métricas por régimen, trades, equity y procedencia en cada JSON.",
    ]
    (store.path / "batch_002_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return store.path
