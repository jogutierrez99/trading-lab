import pandas as pd

from quant_lab.config import StrategyConfig
from quant_lab.strategies.regime_meanrev import RegimeMeanrevStrategy
from quant_lab.strategies.registry import StrategyRegistry


def test_regime_meanrev_long_rules_and_disabled_shorts():
    strategy = (
        StrategyRegistry().discover().create(StrategyConfig(name="regime_meanrev", enabled=True))
    )
    assert isinstance(strategy, RegimeMeanrevStrategy)
    f = pd.DataFrame(
        {
            "close": [95.0] * 6,
            "lower": [96.0] * 6,
            "middle": [97.0] * 6,
            "rsi": [29.0, 29.0, 29.0, 30.0, 56.0, 29.0],
            "adx": [19.0, 20.0, 19.0, 19.0, 19.0, 19.0],
            "distance": [0.04, 0.04, 0.05, 0.04, 0.04, 0.04],
        }
    )
    f.loc[5, "close"] = 98.0
    assert strategy.generate_long_entries(f) == [True, False, False, False, False, False]
    assert strategy.generate_long_exits(f) == [False, False, False, False, True, True]
    assert not any(strategy.generate_short_entries(f))
    assert not any(strategy.generate_short_exits(f))
