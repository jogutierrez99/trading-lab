import pandas as pd

from quant_lab.config import StrategyConfig
from quant_lab.strategies.registry import StrategyRegistry
from quant_lab.strategies.vol_momentum import VolMomentumStrategy


def test_vol_momentum_long_rules_and_disabled_shorts():
    strategy = (
        StrategyRegistry().discover().create(StrategyConfig(name="vol_momentum", enabled=True))
    )
    assert isinstance(strategy, VolMomentumStrategy)
    f = pd.DataFrame(
        {
            "close": [101.0, 101.0, 99.0, 101.0],
            "ema": [100.0] * 4,
            "momentum": [0.1, 0.0, 0.1, 0.1],
            "volatility": [0.8, 0.8, 0.8, 0.0],
        }
    )
    assert strategy.generate_long_entries(f) == [True, False, False, False]
    assert strategy.generate_long_exits(f) == [False, True, True, False]
    assert not any(strategy.generate_short_entries(f))
    assert not any(strategy.generate_short_exits(f))
