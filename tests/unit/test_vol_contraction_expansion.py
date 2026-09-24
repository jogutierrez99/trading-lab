import pandas as pd
import pytest

from quant_lab.config import StrategyConfig
from quant_lab.strategies.registry import StrategyRegistry


def test_vol_contraction_expansion_rules_and_no_shorts():
    strategy = (
        StrategyRegistry()
        .discover()
        .create(StrategyConfig(name="vol_contraction_expansion", enabled=True))
    )
    frame = pd.DataFrame(
        {
            "ema50": [105.0, 105.0, 105.0, 105.0, 105.0],
            "ema200": [100.0, 100.0, 100.0, 100.0, 100.0],
            "roc7": [0.1, 0.1, -0.1, 0.1, 0.1],
            "close": [110.0, 110.0, 110.0, 100.0, 110.0],
            "prior_high": [109.0, 109.0, 109.0, 109.0, 109.0],
            "atr_ratio": [0.04, 0.04, 0.04, 0.04, 0.01],
            "previous_ratio": [0.03, 0.03, 0.03, 0.03, 0.03],
            "p30": [0.02, 0.02, 0.02, 0.02, 0.02],
            "p50": [0.03, 0.03, 0.03, 0.03, 0.03],
            "recent_contractions": [6.0, 5.0, 6.0, 6.0, 6.0],
        }
    )
    assert strategy.generate_long_entries(frame) == [True, False, False, False, False]
    assert strategy.generate_long_exits(frame) == [False, False, True, True, True]
    assert not any(strategy.generate_short_entries(frame))
    assert not any(strategy.generate_short_exits(frame))
    with pytest.raises(ValueError):
        StrategyRegistry().discover().create(
            StrategyConfig(name="vol_contraction_expansion", enabled=True, parameters={"typo": 1})
        )
