import pandas as pd

from quant_lab.config import StrategyConfig
from quant_lab.strategies.registry import StrategyRegistry


def test_ema_pullback_rules_and_no_shorts():
    strategy = (
        StrategyRegistry().discover().create(StrategyConfig(name="ema_pullback", enabled=True))
    )
    frame = pd.DataFrame(
        {
            "previous_touch": [True, False, True],
            "close": [110.0, 110.0, 90.0],
            "pullback_ema": [100.0, 100.0, 100.0],
            "rsi": [60.0, 60.0, 60.0],
            "ema50": [105.0, 105.0, 105.0],
            "ema200": [100.0, 100.0, 100.0],
        }
    )
    assert strategy.generate_long_entries(frame) == [True, False, False]
    assert strategy.generate_long_exits(frame) == [False, False, True]
    assert not any(strategy.generate_short_entries(frame))
    assert not any(strategy.generate_short_exits(frame))
