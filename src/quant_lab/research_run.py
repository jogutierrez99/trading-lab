"""Connect validated history and a registered strategy to a replaceable backend."""

from dataclasses import asdict

import pandas as pd

from quant_lab.backtest import BacktestBackend, BacktestResult, ReferenceBackend
from quant_lab.config import ResearchConfig
from quant_lab.execution_config import ExecutionConfig
from quant_lab.features import atr
from quant_lab.history import HistoryRequest
from quant_lab.history_cache import fingerprint
from quant_lab.indicators import volatility_fractions
from quant_lab.metrics import summarize
from quant_lab.strategies.registry import StrategyRegistry


def run_strategy(
    candles: pd.DataFrame,
    history: HistoryRequest,
    research: ResearchConfig,
    strategy_name: str,
    execution: ExecutionConfig,
    registry: StrategyRegistry,
    backend: BacktestBackend | None = None,
) -> BacktestResult:
    matches = [s for s in research.strategies if s.name == strategy_name]
    if len(matches) != 1:
        raise ValueError(f"Expected one configured strategy: {strategy_name}")
    config = matches[0]
    market = config.market
    if (market.provider, market.symbol, market.timeframe) != (
        history.provider,
        history.symbol,
        history.timeframe,
    ) or market not in research.markets.markets:
        raise ValueError("Strategy market does not match the requested configured dataset")
    if config.risk.stop_enabled and config.risk.stop_method != "atr":
        raise ValueError("Strategy runner currently supports ATR stops only")
    strategy = registry.create(config)
    signals = strategy.generate_signals(candles.copy(deep=True))
    distances = atr(candles, config.risk.atr_period) * config.risk.atr_multiplier
    if config.risk.sizing_method == "volatility_target":
        fractions = volatility_fractions(
            candles.close,
            config.risk.volatility_period,
            config.risk.target_volatility_pct,
            config.risk.min_position_pct,
            min(config.risk.max_position_pct, config.risk.max_exposure_pct),
        )
        return (backend or ReferenceBackend()).run(
            candles,
            signals,
            distances,
            history,
            research.app,
            config.risk,
            execution,
            entry_fractions=fractions,
        )
    return (backend or ReferenceBackend()).run(
        candles, signals, distances, history, research.app, config.risk, execution
    )


def result_document(
    result: BacktestResult,
    candles: pd.DataFrame,
    history: HistoryRequest,
    research: ResearchConfig,
    execution: ExecutionConfig,
    strategy_name: str,
) -> dict:
    return {
        "schema_version": 1,
        "kind": "historical_backtest",
        "backend": "reference_v3"
        if any(
            s.risk.sizing_method == "volatility_target" or s.risk.trailing_basis != "high_low"
            for s in research.strategies
        )
        else "reference_v2",
        "dataset_id": fingerprint(candles, history),
        "strategy": strategy_name,
        "research_config": research.model_dump(mode="json"),
        "history": history.model_dump(mode="json"),
        "execution": execution.model_dump(mode="json"),
        "metrics": summarize(result),
        "trades": [asdict(t) for t in result.trades],
        "rejections": [asdict(r) for r in result.rejections],
        "equity": [{"time": t.isoformat(), "value": float(v)} for t, v in result.equity.items()],
        "open_position": result.open_position,
    }
