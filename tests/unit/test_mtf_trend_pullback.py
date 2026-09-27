"""Registry and directional contract for trend_pullback."""

import pandas as pd
import pytest
from pydantic import ValidationError

from quant_lab.mtf_execution import configuration
from quant_lab.strategies.registry import StrategyRegistry


def test_trend_pullback_contract():
    registry = StrategyRegistry().discover()
    for mode in ("LONG_ONLY", "SHORT_ONLY", "LONG_SHORT"):
        strategy = registry.create(configuration("BTCUSDT", "trend_pullback", "V1", mode))
        f = pd.DataFrame({"long_final": [True, False], "short_final": [False, True]})
        assert strategy.generate_long_entries(f) == (
            [False, False] if mode == "SHORT_ONLY" else [True, False]
        )
        assert strategy.generate_short_entries(f) == (
            [False, False] if mode == "LONG_ONLY" else [False, True]
        )
        assert strategy.generate_long_exits(f) == strategy.generate_short_exits(f) == [False, False]
        assert strategy.metadata()["version"] == "1.0.0"
    bad = configuration("BTCUSDT", "trend_pullback", "V1").model_copy(
        update={"parameters": {"unknown": 1}}
    )
    with pytest.raises(ValidationError):
        registry.create(bad)
