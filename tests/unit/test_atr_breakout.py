import pandas as pd

from quant_lab.config import StrategyConfig
from quant_lab.strategies.registry import StrategyRegistry


def test_atr_breakout_rules_and_no_shorts():
    strategy = (
        StrategyRegistry().discover().create(StrategyConfig(name="atr_breakout", enabled=True))
    )
    frame = pd.DataFrame(
        {
            "close": [110.0, 110.0, 90.0],
            "ema200": [100.0, 100.0, 100.0],
            "ema50": [105.0, 105.0, 105.0],
            "breakout_level": [108.0, 108.0, 95.0],
            "atr_ratio": [0.02, 0.005, 0.02],
            "threshold": [0.01, 0.01, 0.01],
        }
    )
    assert strategy.generate_long_entries(frame) == [True, False, False]
    assert strategy.generate_long_exits(frame) == [False, False, True]
    assert not any(strategy.generate_short_entries(frame))
    assert not any(strategy.generate_short_exits(frame))
