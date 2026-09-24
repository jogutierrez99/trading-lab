import pandas as pd
import pytest

from quant_lab.config import StrategyConfig
from quant_lab.strategies.registry import StrategyRegistry


def test_trend_acceleration_rules_and_no_shorts():
    strategy = (
        StrategyRegistry()
        .discover()
        .create(StrategyConfig(name="trend_acceleration", enabled=True))
    )
    frame = pd.DataFrame(
        {
            "ema50": [105.0, 105.0, 105.0, 105.0],
            "ema200": [100.0, 100.0, 100.0, 100.0],
            "slope_fast": [0.02, 0.02, 0.01, -0.01],
            "slope_slow": [0.01, 0.01, 0.01, 0.01],
            "previous_slope_fast": [0.01, 0.02, 0.02, 0.01],
            "close": [110.0, 110.0, 110.0, 110.0],
            "prior_high": [109.0, 109.0, 109.0, 109.0],
        }
    )
    assert strategy.generate_long_entries(frame) == [True, False, False, False]
    assert strategy.generate_long_exits(frame) == [False, False, False, True]
    assert not any(strategy.generate_short_entries(frame))
    assert not any(strategy.generate_short_exits(frame))
    with pytest.raises(ValueError):
        StrategyRegistry().discover().create(
            StrategyConfig(name="trend_acceleration", enabled=True, parameters={"typo": 1})
        )
