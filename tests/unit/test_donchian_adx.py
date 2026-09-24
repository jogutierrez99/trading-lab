import pandas as pd

from quant_lab.config import StrategyConfig
from quant_lab.strategies.donchian_adx import DonchianAdxStrategy
from quant_lab.strategies.registry import StrategyRegistry


def test_donchian_adx_long_rules_and_disabled_shorts():
    strategy = (
        StrategyRegistry().discover().create(StrategyConfig(name="donchian_adx", enabled=True))
    )
    assert isinstance(strategy, DonchianAdxStrategy)
    f = pd.DataFrame(
        {
            "close": [105.0, 105.0, 105.0, 99.0],
            "ema": [100.0] * 4,
            "upper": [104.0, 104.0, 106.0, 104.0],
            "adx": [21.0, 20.0, 30.0, 30.0],
        }
    )
    assert strategy.generate_long_entries(f) == [True, False, False, False]
    assert strategy.generate_long_exits(f) == [False, False, False, True]
    assert not any(strategy.generate_short_entries(f))
    assert not any(strategy.generate_short_exits(f))
