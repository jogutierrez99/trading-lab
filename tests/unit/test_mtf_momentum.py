import pandas as pd

from quant_lab.config import StrategyConfig
from quant_lab.strategies.registry import StrategyRegistry


def test_mtf_momentum_rules_and_no_shorts():
    strategy = (
        StrategyRegistry().discover().create(StrategyConfig(name="mtf_momentum", enabled=True))
    )
    frame = pd.DataFrame(
        {
            "htf_close": [110.0, 110.0, 110.0],
            "htf_ema50": [105.0, 105.0, 90.0],
            "htf_ema200": [100.0, 100.0, 100.0],
            "htf_momentum": [0.1, 0.1, 0.1],
            "close": [111.0, 99.0, 111.0],
            "prior_high": [110.0, 110.0, 110.0],
        }
    )
    assert strategy.generate_long_entries(frame) == [True, False, False]
    assert strategy.generate_long_exits(frame) == [False, False, True]
    assert not any(strategy.generate_short_entries(frame))
    assert not any(strategy.generate_short_exits(frame))
