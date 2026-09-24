"""Execution-time adapter for absolute long stops; previous engine stays unchanged."""

from dataclasses import replace
from math import isfinite

import pandas as pd

from quant_lab.backtest import ReferenceBackend
from quant_lab.research_run import run_strategy
from quant_lab.risk import CostModel


def run_structural(candles, signals, anchors, atrs, history, app, risk, execution):
    if (
        execution.direction != "long"
        or execution.market_mode != "spot"
        or risk.stop_method != "structure"
        or not risk.stop_enabled
        or risk.trailing_atr_multiplier is not None
        or risk.take_profit_enabled
    ):
        raise ValueError(
            "Absolute stop adapter requires spot long, structure stop, no target/trailing"
        )
    if not anchors.index.equals(candles.index) or not atrs.index.equals(candles.index):
        raise ValueError("Structural inputs must align exactly")
    distances = pd.Series(float("nan"), index=candles.index)
    reasons = {}
    costs = CostModel.from_config(app.costs)
    # This is order execution, not a feature: only the next bar's OPEN is consulted.
    # Distances are stored in the previous-row slot expected by ReferenceBackend.
    for i in range(1, len(candles)):
        anchor, cap = float(anchors.iloc[i - 1]), float(atrs.iloc[i - 1]) * risk.atr_multiplier
        opening = float(candles.open.iloc[i])
        entry = costs.price(opening, 1)
        distance = entry - anchor
        if not isfinite(anchor) or not isfinite(cap) or anchor <= 0 or cap <= 0:
            reason = "invalid_structural_anchor"
        elif opening <= anchor:
            reason = "open_at_or_below_structural_stop"
        elif not 0 < distance <= cap:
            reason = "structural_distance_exceeds_atr_cap"
        else:
            distances.iloc[i - 1] = distance
            continue
        reasons[candles.index[i]] = reason
    result = ReferenceBackend().run(candles, signals, distances, history, app, risk, execution)
    return replace(
        result,
        rejections=tuple(
            replace(r, reason=reasons[r.time])
            if r.reason == "invalid_stop_distance" and r.time in reasons
            else r
            for r in result.rejections
        ),
    )


def run_strategy005(candles, history, research, name, execution, registry):
    if name != "channel_break_retest":
        return run_strategy(candles, history, research, name, execution, registry)
    matches = [s for s in research.strategies if s.name == name]
    if len(matches) != 1:
        raise ValueError("Expected one configured structural strategy")
    config = matches[0]
    if (config.market.provider, config.market.symbol, config.market.timeframe) != (
        history.provider,
        history.symbol,
        history.timeframe,
    ) or config.market not in research.markets.markets:
        raise ValueError("Structural strategy market does not match history")
    strategy = registry.create(config)
    features = strategy.prepare_features(candles)
    signals = strategy.generate_signals(candles)
    return run_structural(
        candles,
        signals,
        features.stop_anchor,
        features.atr,
        history,
        research.app,
        config.risk,
        execution,
    )
