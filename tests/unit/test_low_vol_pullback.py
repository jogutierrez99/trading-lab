import pandas as pd
import pytest

from quant_lab.config import StrategyConfig
from quant_lab.strategies.registry import StrategyRegistry


def test_low_vol_pullback_gates_exits_and_disabled_shorts():
    strategy = (
        StrategyRegistry().discover().create(StrategyConfig(name="low_vol_pullback", enabled=True))
    )
    base = {
        "close": 110.0,
        "ema20": 108.0,
        "ema50": 105.0,
        "ema200": 100.0,
        "rsi": 60.0,
        "previous_touch": True,
        "atr_ratio": 0.01,
        "threshold": 0.02,
        "exit_threshold": 0.03,
    }
    gates = [
        {"ema50": 100.0},
        {"close": 100.0},
        {"previous_touch": False},
        {"ema20": 110.0},
        {"rsi": 50.0},
        {"atr_ratio": 0.02},
    ]
    frame = pd.DataFrame([base] + [base | g for g in gates])
    assert strategy.generate_long_entries(frame) == [True] + [False] * len(gates)
    assert strategy.generate_long_exits(pd.DataFrame([base])) == [False]
    exits = [{"close": 104.0}, {"atr_ratio": 0.04}]
    assert all(strategy.generate_long_exits(pd.DataFrame([base | e for e in exits])))
    assert not any(strategy.generate_short_entries(frame))
    assert not any(strategy.generate_short_exits(frame))
    with pytest.raises(ValueError):
        StrategyRegistry().discover().create(
            StrategyConfig(name="low_vol_pullback", enabled=True, parameters={"typo": 1})
        )
