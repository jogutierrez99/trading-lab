"""Lagged momentum uses completed historical observations only."""

import pandas as pd

from quant_lab.config import StrategyConfig
from quant_lab.strategies.registry import StrategyRegistry
from quant_lab.strategies.time_series_momentum import TimeSeriesMomentumStrategy


def test_time_series_momentum_formula_and_sides():
    registry = StrategyRegistry().discover()
    assert "time_series_momentum" in registry.names()
    config = StrategyConfig(
        name="time_series_momentum", enabled=True, parameters={"lookback_days": 1}
    )
    strategy = registry.create(config)
    assert isinstance(strategy, TimeSeriesMomentumStrategy)
    assert strategy.metadata()["version"] == "1.0.0"
    close = pd.Series([100.0] * 25 + [200.0, 1.0, 100.0])
    frame = pd.DataFrame({"close": close})
    features = strategy.prepare_features(frame)
    assert features.momentum.iloc[:25].isna().all()
    assert features.momentum.iloc[25] == 0
    assert features.momentum.iloc[26] == 1
    assert features.momentum.iloc[27] == -0.99
    signals = strategy.generate_signals(frame)
    assert signals.long_entries[26] and signals.short_exits[26]
    assert signals.short_entries[27] and signals.long_exits[27]
