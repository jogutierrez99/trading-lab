"""Reusable recording of a single temporal, independent-account experiment."""

import math
from dataclasses import asdict

import pandas as pd

from quant_lab.backtest import ReferenceBackend
from quant_lab.batch import COSTS, Candidate, Window, resolve_candidate
from quant_lab.batch_003_analysis import extended_metrics
from quant_lab.batch_004_analysis import LABEL, regime_analysis
from quant_lab.candles import validate_candles
from quant_lab.config import ResearchConfig, RiskConfig
from quant_lab.entry_diagnostics import entry_diagnostics
from quant_lab.execution_config import ExecutionConfig
from quant_lab.experiments import ExperimentStore, write_json
from quant_lab.history import HistoryRequest
from quant_lab.history_cache import fingerprint
from quant_lab.indicators import volatility_fractions
from quant_lab.metrics import daily_returns
from quant_lab.research_run import result_document
from quant_lab.strategies.base import Signals
from quant_lab.strategies.registry import StrategyRegistry
from quant_lab.structural_execution import run_strategy005


def bounded_view(candles: pd.DataFrame, parent: HistoryRequest, window: Window, warmup: int):
    if not parent.start <= window.start < window.end <= parent.end:
        raise ValueError("Window outside validated study")
    request = HistoryRequest.model_validate(
        parent.model_dump() | {"start": window.start, "end": window.end, "warmup_bars": warmup}
    )
    frame = candles.loc[
        (candles.index >= request.download_start) & (candles.index < request.end)
    ].copy()
    validate_candles(frame, request)
    return frame, request


class Batch005Executor:
    def __init__(
        self,
        store: ExperimentStore,
        research: ResearchConfig,
        execution: ExecutionConfig,
        registry: StrategyRegistry,
    ):
        self.store, self.research, self.execution, self.registry = (
            store,
            research,
            execution,
            registry,
        )
        self.rows: list[dict] = []

    def execute(
        self,
        candidate: Candidate,
        candles: pd.DataFrame,
        parent: HistoryRequest,
        window: Window,
        partition: str,
        scenario: str,
        warmup: int = 768,
        dataset_label: str = "primary",
        benchmark_pct: float | None = None,
    ) -> dict:
        metadata = {
            "interpretation": LABEL,
            "role": "REFERENCE_DIAGNOSTIC" if partition.startswith("reference_") else "EXPERIMENT",
            "candidate": candidate.id,
            "strategy": candidate.strategy,
            "partition": partition,
            "costs": scenario,
            "window": window.model_dump(mode="json"),
            "parent_dataset_id": fingerprint(candles, parent),
            "dataset_label": dataset_label,
            "warmup_bars": warmup,
            "benchmark_pct": benchmark_pct,
        }
        resolved = resolve_candidate(self.research, candidate)
        resolved = resolved.model_copy(
            update={"app": resolved.app.model_copy(update={"costs": COSTS[scenario]})}
        )
        metadata["resolved_config"] = resolved.model_dump(mode="json")
        ident = self.store.start(metadata)
        try:
            frame, history = bounded_view(candles, parent, window, warmup)
            if benchmark_pct is None:
                result = run_strategy005(
                    frame, history, resolved, candidate.strategy, self.execution, self.registry
                )
            else:
                risk = RiskConfig(
                    sizing_method="fixed_notional",
                    position_pct=benchmark_pct,
                    max_position_pct=benchmark_pct,
                    stop_enabled=False,
                    take_profit_enabled=False,
                )
                empty = (False,) * len(frame)
                entries = tuple(t == window.start for t in frame.index)
                result = ReferenceBackend().run(
                    frame,
                    Signals(entries, empty, empty, empty),
                    pd.Series(float("nan"), index=frame.index),
                    history,
                    resolved.app,
                    risk,
                    self.execution,
                )
            document = result_document(
                result, frame, history, resolved, self.execution, candidate.strategy
            )
            document["experiment"] = metadata | {"experiment_id": ident}
            if benchmark_pct is not None:
                document["kind"] = "buy_and_hold_benchmark"
                document["benchmark_risk"] = risk.model_dump()
            risk = resolved.strategies[0].risk
            if benchmark_pct is None and risk.sizing_method == "volatility_target":
                fractions = volatility_fractions(
                    frame.close,
                    risk.volatility_period,
                    risk.target_volatility_pct,
                    risk.min_position_pct,
                    min(risk.max_position_pct, risk.max_exposure_pct),
                )
                used = [
                    float(fractions.loc[t.signal_close - pd.Timedelta(hours=1)])
                    for t in result.trades
                ]
                document["entry_exposure_fraction"] = used
            quality, edge, extra_metrics = entry_diagnostics(frame, result)
            document["entry_quality"] = quality
            document["time_to_edge"] = edge
            document["metrics"].update(extra_metrics)
            if candidate.strategy == "channel_break_retest" and benchmark_pct is None:
                document["backend"] = "reference_v2_with_absolute_stop_adapter_v1"
                document["structural_stop"] = {
                    "mode": "absolute_retest_low_minus_0.01_ATR_at_retest",
                    "maximum_distance": "2.5 ATR at confirmation, checked against next-open "
                    "cost-adjusted entry",
                    "gap_policy": "reject open<=anchor or distance outside (0,cap]",
                }
            document["interpretation"] = LABEL
            document["metrics"].update(extended_metrics(result))
            document["regimes"] = regime_analysis(frame, result)
            balance = float(result.equity.iloc[0])
            for trade in result.trades:
                if trade.entry_time != trade.signal_close:
                    raise AssertionError("Fill must use the open immediately after signal close")
                if not window.start < trade.entry_time < window.end:
                    raise AssertionError("Entry outside scoring period")
                if benchmark_pct is None:
                    cap = min(risk.max_position_pct, risk.max_exposure_pct) / 100
                    if trade.quantity * trade.entry_price + trade.entry_fee > balance * cap + 1e-7:
                        raise AssertionError("Entry exposure exceeds configured cap")
                    if (
                        risk.sizing_method == "stop_risk"
                        and trade.expected_stop_loss
                        > balance * risk.risk_per_trade_pct / 100 + 1e-7
                    ):
                        raise AssertionError("Initial estimated risk exceeds budget")
                balance += trade.net_pnl
            if result.open_position is not None or not math.isclose(
                balance, result.equity.iloc[-1], abs_tol=1e-6
            ):
                raise AssertionError("Closed trades do not reconcile to final equity")
            if not math.isclose(
                document["metrics"]["gross_pnl"] - document["metrics"]["total_costs"],
                balance - result.equity.iloc[0],
                abs_tol=1e-6,
            ):
                raise AssertionError("Gross/net/cost reconciliation failed")
            document["audit"] = {
                "closed_and_reconciled": True,
                "entry_caps_and_initial_risk": True,
                "entry_timing": (
                    "Signal close equals following bar open boundary; originating candle "
                    "open is one hour earlier"
                ),
            }
            daily = daily_returns(result.equity)
            document["monthly_returns_pct"] = {
                str(k.date()): float(v)
                for k, v in ((1 + daily).resample("MS").prod() - 1).mul(100).items()
            }
            document["yearly_returns_pct"] = {
                str(k.year): float(v)
                for k, v in ((1 + daily).resample("YS").prod() - 1).mul(100).items()
            }
            artifact = self.store.path / ident
            pd.DataFrame({"equity": result.equity, "close_exposure": result.exposure}).to_parquet(
                artifact / "equity.parquet"
            )
            write_json(self.store.path / "results" / f"{ident}.json", document)
            pd.DataFrame(
                [
                    asdict(t)
                    | quality["trades"][i]
                    | {
                        f"asset_return_{h}h_pct": v
                        for h, v in edge["trades"][i]["returns_pct"].items()
                    }
                    for i, t in enumerate(result.trades)
                ]
            ).to_parquet(self.store.path / "trades" / f"{ident}.parquet")
            pd.DataFrame({"equity": result.equity, "close_exposure": result.exposure}).to_parquet(
                self.store.path / "equity" / f"{ident}.parquet"
            )
            self.store.finish(ident, document)
            row = {k: v for k, v in metadata.items() if k != "resolved_config"}
            row |= {"experiment_id": ident} | document["metrics"]
            self.rows.append(row)
            print(
                f"{partition} {candidate.id} {scenario} {benchmark_pct or ''}: "
                f"{row['return_pct']:.3f}% ({row['closed_trades']} trades)",
                flush=True,
            )
            return row
        except Exception as exc:
            self.store.finish(ident, {"error": f"{type(exc).__name__}: {exc}"}, "failed")
            raise


def report_table(rows: list[dict]) -> list[str]:
    def fmt(value):
        return "N/D" if value is None else f"{value:.2f}"

    lines = [
        "| Variante | Costes | Retorno % | CAGR % | DD % | Sharpe | Sortino | Trades |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['candidate']} | {row['costs']} | {row['return_pct']:.2f} | "
            f"{fmt(row['cagr_pct'])} | {row['max_drawdown_pct']:.2f} | "
            f"{fmt(row['sharpe'])} | {fmt(row['sortino'])} | {row['closed_trades']} |"
        )
    return lines
