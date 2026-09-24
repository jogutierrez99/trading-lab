"""Offline, preregistered temporal experiments. Selection consumes train only."""

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import Field, model_validator

from quant_lab.backtest import ReferenceBackend
from quant_lab.candles import validate_candles
from quant_lab.config import (
    CostsConfig,
    ResearchConfig,
    RiskConfig,
    StrategyConfig,
    StrictModel,
    load_research_config,
    load_yaml,
)
from quant_lab.execution_config import ExecutionConfig
from quant_lab.experiments import ExperimentStore, provenance, write_json
from quant_lab.features import atr, ema
from quant_lab.history import HistoryRequest
from quant_lab.history_cache import fingerprint, read_bundle
from quant_lab.metrics import daily_returns
from quant_lab.research_run import result_document, run_strategy
from quant_lab.strategies.base import Signals
from quant_lab.strategies.registry import StrategyRegistry


class Window(StrictModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def check(self):
        HistoryRequest(start=self.start, end=self.end, warmup_bars=0)
        if self.start.hour or self.end.hour:
            raise ValueError("Batch partitions must be UTC midnight aligned")
        return self


class Candidate(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    strategy: str
    baseline: bool = False
    parameters: dict[str, Any] = Field(default_factory=dict)
    risk: dict[str, Any] = Field(default_factory=dict)


class BatchPlan(StrictModel):
    app_file: str
    execution_file: str
    history_file: str
    dataset_dir: str
    output_dir: str
    train: Window
    validation: Window
    test: Window
    walk_forward: list[Window] = Field(default_factory=list)
    candidates: list[Candidate] = Field(min_length=1)

    @model_validator(mode="after")
    def check(self):
        if self.train.end != self.validation.start or self.validation.end != self.test.start:
            raise ValueError("Train/validation/test must be ordered and adjacent")
        ids = [c.id for c in self.candidates]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate candidate IDs")
        for name in {c.strategy for c in self.candidates}:
            if sum(c.baseline for c in self.candidates if c.strategy == name) != 1:
                raise ValueError("Each strategy needs exactly one baseline")
        previous_end = self.train.start
        for window in self.walk_forward:
            if not (self.train.start < window.start < window.end <= self.test.start):
                raise ValueError("Walk-forward must precede final test")
            if window.start < previous_end:
                raise ValueError("Walk-forward tests cannot overlap")
            previous_end = window.end
        return self


COSTS = {
    "zero": CostsConfig(trading_fee_pct=0.0, slippage_pct=0.0, spread_pct=0.0),
    "base": CostsConfig(trading_fee_pct=0.05, slippage_pct=0.02, spread_pct=0.01),
    "adverse": CostsConfig(trading_fee_pct=0.10, slippage_pct=0.10, spread_pct=0.02),
}


def window_view(candles: pd.DataFrame, parent: HistoryRequest, window: Window):
    if not parent.start <= window.start < window.end <= parent.end:
        raise ValueError("Partition is outside the validated study")
    warmup = int((pd.Timestamp(window.start) - candles.index[0]) / pd.Timedelta(hours=1))
    request = HistoryRequest.model_validate(
        parent.model_dump()
        | {
            "start": window.start,
            "end": window.end,
            "warmup_bars": warmup,
        }
    )
    frame = candles.loc[candles.index < window.end].copy()
    validate_candles(frame, request)
    return frame, request


def resolve_candidate(research: ResearchConfig, candidate: Candidate) -> ResearchConfig:
    base = next((s for s in research.strategies if s.name == candidate.strategy), None)
    if base is None or not base.enabled:
        raise ValueError(f"Candidate references absent/disabled strategy: {candidate.strategy}")
    config = StrategyConfig.model_validate(
        base.model_dump()
        | {
            "parameters": base.parameters | candidate.parameters,
            "risk": base.risk.model_dump() | candidate.risk,
        }
    )
    return research.model_copy(update={"strategies": (config,)})


def select_candidate(rows: list[dict], baseline_id: str) -> tuple[str, bool]:
    if any(r["partition"] != "train" or r["costs"] != "base" for r in rows):
        raise ValueError("Selection accepts base-cost train results only")
    eligible = [
        r
        for r in rows
        if r["closed_trades"] >= 20
        and r["return_pct"] > 0
        and r["max_drawdown_pct"] <= 25
        and r["sharpe"] is not None
    ]
    eligible.sort(key=lambda r: (-r["sharpe"], r["turnover_initial_equity"], r["candidate"]))
    return (eligible[0]["candidate"], True) if eligible else (baseline_id, False)


def classify(base: dict, zero: dict) -> dict:
    flags = {
        "small_sample": base["closed_trades"] < 30 or base["observed_days"] < 90,
        "undefined_metrics": any(base[k] is None for k in ("sharpe", "sortino", "profit_factor")),
        "failed_after_costs": zero["return_pct"] > 0 >= base["return_pct"],
        "failed_oos": base["return_pct"] <= 0
        or base["max_drawdown_pct"] > 25
        or (base["profit_factor"] is not None and base["profit_factor"] < 1),
    }
    label = "PROMISING_BUT_UNSTABLE"
    if flags["small_sample"] or flags["undefined_metrics"]:
        label = "INSUFFICIENT_DATA"
    elif flags["failed_after_costs"]:
        label = "FAILED_AFTER_COSTS"
    elif flags["failed_oos"]:
        label = "FAILED_OOS"
    return {"classification": label, "flags": flags}


def regime_report(frame: pd.DataFrame, result) -> dict:
    trend = pd.Series("unknown", index=frame.index)
    average = ema(frame.close, 200)
    trend.loc[average.notna() & (frame.close >= average)] = "above_ema200"
    trend.loc[average.notna() & (frame.close < average)] = "below_ema200"
    normalized = atr(frame, 14) / frame.close
    median = normalized.shift(1).rolling(720).median()
    volatility = pd.Series("unknown", index=frame.index)
    volatility.loc[median.notna() & (normalized >= median)] = "high_vol"
    volatility.loc[median.notna() & (normalized < median)] = "low_vol"
    labels = trend + "/" + volatility
    trades: dict[str, dict] = {}
    for trade in result.trades:
        key = labels.loc[trade.signal_close - pd.Timedelta(hours=1)]
        group = trades.setdefault(key, {"trades": 0, "net_pnl": 0.0})
        group["trades"] += 1
        group["net_pnl"] += trade.net_pnl
    daily = daily_returns(result.equity)
    known = labels.copy()
    known.index += pd.Timedelta(hours=1)
    day_labels = known.reindex(daily.index, method="ffill").fillna("unknown")
    grouped = pd.DataFrame({"return": daily, "regime": day_labels}).groupby("regime")
    return {
        "trades_by_signal_regime": trades,
        "daily_returns_by_start_regime": {
            str(key): {"days": len(group), "mean_return_pct": float(group["return"].mean() * 100)}
            for key, group in grouped
        },
    }


def run_batch(plan_path: Path, repo_root: Path) -> Path:
    plan = load_yaml(plan_path, BatchPlan)
    directory = plan_path.resolve().parent
    research = load_research_config(directory / plan.app_file)
    execution = load_yaml(directory / plan.execution_file, ExecutionConfig)
    if execution.market_mode != "spot" or execution.direction != "long":
        raise ValueError("Batch 001 is spot long only")
    if not execution.liquidate_at_end:
        raise ValueError("Batch partitions require terminal liquidation")
    parent = load_yaml(directory / plan.history_file, HistoryRequest)
    candles = read_bundle(directory / plan.dataset_dir, parent)
    parent_id = fingerprint(candles, parent)
    registry = StrategyRegistry().discover()
    for candidate in plan.candidates:
        resolved = resolve_candidate(research, candidate)
        registry.create(resolved.strategies[0])
    # Freeze executable plan, configs, costs, dataset and code BEFORE any backtest.
    store = ExperimentStore(
        directory / plan.output_dir,
        {
            "plan": plan.model_dump(mode="json"),
            "research": research.model_dump(mode="json"),
            "execution": execution.model_dump(mode="json"),
            "parent_dataset_id": parent_id,
            "costs": {k: v.model_dump() for k, v in COSTS.items()},
            "selection": "train_base: trades>=20, return>0, DD<=25; max Sharpe, min turnover, ID",
            "robust_label_enabled": False,
        },
        provenance(repo_root),
    )
    rows = []

    def execute(
        candidate: Candidate,
        window: Window,
        partition: str,
        scenario: str,
        benchmark_pct: float | None = None,
    ):
        metadata = {
            "candidate": candidate.id,
            "strategy": candidate.strategy,
            "partition": partition,
            "costs": scenario,
            "window": window.model_dump(mode="json"),
            "parent_dataset_id": parent_id,
            "benchmark_pct": benchmark_pct,
        }
        experiment_id = store.start(metadata)
        try:
            frame, history = window_view(candles, parent, window)
            resolved = resolve_candidate(research, candidate)
            resolved = resolved.model_copy(
                update={"app": resolved.app.model_copy(update={"costs": COSTS[scenario]})}
            )
            if benchmark_pct is None:
                result = run_strategy(
                    frame, history, resolved, candidate.strategy, execution, registry
                )
            else:
                risk = RiskConfig(
                    sizing_method="fixed_notional",
                    position_pct=benchmark_pct,
                    max_position_pct=benchmark_pct,
                    stop_enabled=False,
                    take_profit_enabled=False,
                )
                # Same first tradable next-open as strategies, entered only once.
                entries = tuple(t == window.start for t in frame.index)
                empty = (False,) * len(frame)
                result = ReferenceBackend().run(
                    frame,
                    Signals(entries, empty, empty, empty),
                    pd.Series(float("nan"), index=frame.index),
                    history,
                    resolved.app,
                    risk,
                    execution,
                )
            document = result_document(
                result, frame, history, resolved, execution, candidate.strategy
            )
            document["experiment"] = metadata | {"experiment_id": experiment_id}
            if benchmark_pct is not None:
                document["kind"] = "buy_and_hold_benchmark"
                document["benchmark_risk"] = risk.model_dump()
            document["regimes"] = regime_report(frame, result)
            daily = daily_returns(result.equity)
            document["monthly_returns_pct"] = {
                str(k.date()): float(v)
                for k, v in ((1 + daily).resample("MS").prod() - 1).mul(100).items()
            }
            document["yearly_returns_pct"] = {
                str(k.year): float(v)
                for k, v in ((1 + daily).resample("YS").prod() - 1).mul(100).items()
            }
            artifact = store.path / experiment_id
            pd.DataFrame({"equity": result.equity, "close_exposure": result.exposure}).to_parquet(
                artifact / "equity.parquet"
            )
            pd.DataFrame(document["trades"]).to_json(
                artifact / "trades.json", orient="records", date_format="iso", indent=2
            )
            store.finish(experiment_id, document)
            row = metadata | {"experiment_id": experiment_id} | document["metrics"]
            rows.append(row)
            print(f"{partition} {candidate.id} {scenario}: {row['return_pct']:.3f}%", flush=True)
            return row
        except Exception as exc:
            store.finish(experiment_id, {"error": f"{type(exc).__name__}: {exc}"}, "failed")
            raise

    baselines = {c.strategy: c for c in plan.candidates if c.baseline}
    candidates = {c.id: c for c in plan.candidates}

    def train_and_select(window: Window, label: str):
        trials = [execute(c, window, label, "base") for c in plan.candidates]
        selections = {}
        for name, baseline in baselines.items():
            subset = [dict(r, partition="train") for r in trials if r["strategy"] == name]
            choice, eligible = select_candidate(subset, baseline.id)
            selections[name] = {
                "candidate": choice,
                "train_eligible": eligible,
                "positive_train_fraction": sum(
                    r["return_pct"] > 0 and r["max_drawdown_pct"] <= 25 for r in subset
                )
                / len(subset),
            }
        write_json(store.path / f"selection_{label}.json", selections)
        return selections

    selected = train_and_select(plan.train, "train")
    classifications = {}
    for name, choice in selected.items():
        candidate = candidates[choice["candidate"]]
        for partition in ("validation", "test"):
            scores = {
                scenario: execute(candidate, getattr(plan, partition), partition, scenario)
                for scenario in COSTS
            }
            if partition == "test":
                classifications[name] = classify(scores["base"], scores["zero"]) | choice
                classifications[name]["sensitivity_pass"] = (
                    choice["positive_train_fraction"] >= 0.5 and scores["adverse"]["return_pct"] > 0
                )
    # Walk-forward uses only previous months; its test windows exclude final test.
    wf_rows = []
    for i, window in enumerate(plan.walk_forward):
        selections = train_and_select(
            Window(start=plan.train.start, end=window.start), f"wf{i}_train"
        )
        for choice in selections.values():
            wf_rows.append(execute(candidates[choice["candidate"]], window, f"wf{i}_test", "base"))
    write_json(
        store.path / "walk_forward.json",
        {
            "note": "Overlaps static train/validation; not independent evidence. "
            "No final test used.",
            "test_only": wf_rows,
            "compounded_test_return_pct": {
                name: float(
                    (
                        pd.Series(
                            [1 + r["return_pct"] / 100 for r in wf_rows if r["strategy"] == name]
                        ).prod()
                        - 1
                    )
                    * 100
                )
                for name in baselines
            }
            if wf_rows
            else {},
            "capital_policy": "Reset 10000 per fold; compounded percentage is descriptive, "
            "not a portfolio",
        },
    )
    full = Window(start=plan.train.start, end=plan.test.end)
    for baseline in baselines.values():
        execute(baseline, full, "full_baseline_diagnostic", "base")
    first = next(iter(baselines.values()))
    for partition in ("train", "validation", "test", "full_baseline_diagnostic"):
        for scenario in COSTS if partition != "full_baseline_diagnostic" else ["base"]:
            for pct in (25.0, 100.0):
                execute(
                    first,
                    full if partition == "full_baseline_diagnostic" else getattr(plan, partition),
                    f"benchmark_{partition}",
                    scenario,
                    pct,
                )
    blocked = store.start({"strategy": "CRYPTO_001", "status_reason": "BLOCKED_DATA"})
    store.finish(
        blocked,
        {
            "classification": "INSUFFICIENT_DATA",
            "reason": "No perpetual/funding dataset or multipleg execution",
        },
        "skipped",
    )
    write_json(store.path / "classifications.json", classifications)
    pd.DataFrame(rows).to_csv(store.path / "metrics.csv", index=False)
    write_summary(store.path, rows, classifications, plan)
    return store.path


def write_summary(path: Path, rows: list[dict], classifications: dict, plan: BatchPlan):
    lines = [
        "# Batch 001A — BTC/USDT spot 1h, solo largos",
        "",
        "Capital independiente: 10.000 USDT por ejecución; sin apalancamiento.",
        "Costes base por orden: fee 0,05%, slippage 0,02%, spread completo 0,01%.",
        "Supuestos de simulación, no tarifas históricas verificadas.",
        "",
        f"Train: {plan.train.start.date()}–{plan.train.end.date()}; "
        f"validation: {plan.validation.start.date()}–{plan.validation.end.date()}; "
        f"test: {plan.test.start.date()}–{plan.test.end.date()}. Fin exclusivo UTC.",
        "",
    ]
    for partition, heading in (
        ("full_baseline_diagnostic", "Baselines: periodo completo, descriptivo"),
        ("train", "Entrenamiento: todas las variantes"),
        ("validation", "Validación: candidatos congelados"),
        ("test", "Test reservado: candidatos congelados"),
    ):
        lines += [
            f"## {heading}",
            "",
            "| Configuración | Retorno neto | DD máx. | Sharpe | PF | Trades | Fees USDT |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for row in rows:
            if row["partition"] == partition and row["costs"] == "base":

                def fmt(value):
                    return "N/D" if value is None else f"{value:.2f}"

                lines.append(
                    f"| {row['candidate']} | {row['return_pct']:.2f}% | "
                    f"{row['max_drawdown_pct']:.2f}% | {fmt(row['sharpe'])} | "
                    f"{fmt(row['profit_factor'])} | {row['closed_trades']} | "
                    f"{row['fees_paid']:.2f} |"
                )
        lines.append("")
    lines += ["## Diagnóstico", ""]
    for name, value in classifications.items():
        lines.append(
            f"- {name}: **{value['classification']}**; candidato {value['candidate']}; "
            f"elegible en train: {value['train_eligible']}; flags: {value['flags']}."
        )
    lines += [
        "- CRYPTO_001: **INSUFFICIENT_DATA / BLOCKED_DATA**, sin backtest.",
        "",
        "Comparaciones de costes, benchmarks, Sortino, regímenes y periodos están en metrics.csv "
        "y result.json de cada experimento. Walk-forward usa solo sus ventanas test; "
        "se solapa con train/validation y no es evidencia independiente.",
        "",
        "No hay ganador declarado ni etiqueta ROBUST. El periodo completo es descriptivo; "
        "la selección usa solo train. Las muestras pequeñas pueden ocultar fallos adicionales: "
        "consultar flags. Funding no aplica al spot; cortos y perpetuals no se han simulado.",
        "",
        "Ledger: ledger.sqlite. Plan/config/código congelados antes de ejecutar. "
        "Cada carpeta contiene métricas, trades, equity y procedencia del dataset derivado.",
    ]
    with (path / "batch_001_summary.md").open("x", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
