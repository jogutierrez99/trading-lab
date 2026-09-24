import pandas as pd
import pytest

from quant_lab.config import StrategyConfig
from quant_lab.strategies.registry import StrategyRegistry


def test_vol_expansion_trend_gates_exits_and_disabled_shorts():
    strategy = (
        StrategyRegistry()
        .discover()
        .create(StrategyConfig(name="vol_expansion_trend", enabled=True))
    )
    base = {
        "close": 110.0,
        "ema50": 105.0,
        "ema200": 100.0,
        "roc7": 0.1,
        "atr_ratio": 0.03,
        "threshold": 0.01,
        "ratio_sma24": 0.02,
        "prior_high": 109.0,
    }
    gates = [
        {"ema50": 100.0},
        {"roc7": 0.0},
        {"atr_ratio": 0.02},
        {"threshold": 0.03},
        {"close": 109.0},
    ]
    frame = pd.DataFrame([base] + [base | g for g in gates])
    assert strategy.generate_long_entries(frame) == [True] + [False] * len(gates)
    assert strategy.generate_long_exits(pd.DataFrame([base])) == [False]
    exits = [{"close": 104.0}, {"roc7": -0.1, "atr_ratio": 0.01}]
    assert all(strategy.generate_long_exits(pd.DataFrame([base | e for e in exits])))
    assert not any(strategy.generate_short_entries(frame))
    assert not any(strategy.generate_short_exits(frame))
    with pytest.raises(ValueError):
        StrategyRegistry().discover().create(
            StrategyConfig(name="vol_expansion_trend", enabled=True, parameters={"typo": 1})
        )
