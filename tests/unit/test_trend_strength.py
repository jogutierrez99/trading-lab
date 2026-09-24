import pandas as pd

from quant_lab.config import StrategyConfig
from quant_lab.strategies.registry import StrategyRegistry


def test_trend_strength_rules_and_no_shorts():
    strategy = (
        StrategyRegistry().discover().create(StrategyConfig(name="trend_strength", enabled=True))
    )
    frame = pd.DataFrame(
        {
            "close": [110.0, 110.0, 90.0],
            "ema50": [105.0, 105.0, 105.0],
            "ema200": [100.0, 100.0, 100.0],
            "ema50_prior": [104.0, 104.0, 104.0],
            "roc_short": [0.1, -0.1, 0.1],
            "roc_long": [0.2, 0.2, 0.2],
            "prior_high": [109.0, 109.0, 109.0],
        }
    )
    assert strategy.generate_long_entries(frame) == [True, False, False]
    assert strategy.generate_long_exits(frame) == [False, True, True]
    assert not any(strategy.generate_short_entries(frame))
    assert not any(strategy.generate_short_exits(frame))
