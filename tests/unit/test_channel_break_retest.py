import pandas as pd
import pytest

from quant_lab.config import StrategyConfig
from quant_lab.strategies.registry import StrategyRegistry


def test_channel_break_retest_rules_and_no_shorts():
    strategy = (
        StrategyRegistry()
        .discover()
        .create(StrategyConfig(name="channel_break_retest", enabled=True))
    )
    frame = pd.DataFrame({"entry": [True, False], "close": [110.0, 90.0], "ema50": [100.0, 100.0]})
    assert strategy.generate_long_entries(frame) == [True, False]
    assert strategy.generate_long_exits(frame) == [False, True]
    assert not any(strategy.generate_short_entries(frame))
    assert not any(strategy.generate_short_exits(frame))
    with pytest.raises(ValueError):
        StrategyRegistry().discover().create(
            StrategyConfig(name="channel_break_retest", enabled=True, parameters={"typo": 1})
        )
