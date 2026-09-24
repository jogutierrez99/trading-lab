import pandas as pd

from quant_lab.config import StrategyConfig
from quant_lab.strategies.bb_squeeze import BbSqueezeStrategy
from quant_lab.strategies.registry import StrategyRegistry


def test_bb_squeeze_long_rules_and_disabled_shorts():
    strategy = StrategyRegistry().discover().create(StrategyConfig(name="bb_squeeze", enabled=True))
    assert isinstance(strategy, BbSqueezeStrategy)
    f = pd.DataFrame(
        {
            "close": [105.0, 105.0, 102.0, 99.0],
            "ema": [100.0] * 4,
            "upper": [104.0] * 4,
            "middle": [101.0] * 4,
            "recent_squeeze": [1.0, 0.0, 1.0, 1.0],
        }
    )
    assert strategy.generate_long_entries(f) == [True, False, False, False]
    assert strategy.generate_long_exits(f) == [False, False, False, True]
    assert not any(strategy.generate_short_entries(f))
    assert not any(strategy.generate_short_exits(f))
