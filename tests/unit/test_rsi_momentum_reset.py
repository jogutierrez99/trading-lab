import pandas as pd
import pytest

from quant_lab.config import StrategyConfig
from quant_lab.strategies.registry import StrategyRegistry


def test_rsi_momentum_reset_rules_and_no_shorts():
    strategy = (
        StrategyRegistry()
        .discover()
        .create(StrategyConfig(name="rsi_momentum_reset", enabled=True))
    )
    frame = pd.DataFrame(
        {
            "entry": [True, False, False, False],
            "close": [110.0, 90.0, 110.0, 110.0],
            "ema50": [100.0, 100.0, 100.0, 100.0],
            "rsi": [55.0, 55.0, 71.0, 55.0],
            "roc30": [0.1, 0.1, 0.1, -0.1],
        }
    )
    assert strategy.generate_long_entries(frame) == [True, False, False, False]
    assert strategy.generate_long_exits(frame) == [False, True, True, True]
    assert not any(strategy.generate_short_entries(frame))
    assert not any(strategy.generate_short_exits(frame))
    with pytest.raises(ValueError):
        StrategyRegistry().discover().create(
            StrategyConfig(name="rsi_momentum_reset", enabled=True, parameters={"typo": 1})
        )
