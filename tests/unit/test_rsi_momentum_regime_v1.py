import pandas as pd
import pytest

from quant_lab.config import MarketConfig, StrategyConfig
from quant_lab.strategies.rsi_momentum_regime_v1 import RsiMomentumRegimeV1Strategy


@pytest.mark.parametrize("side", [1, -1])
def test_rsi_directional_strength_is_not_contrarian(side):
    s = RsiMomentumRegimeV1Strategy(
        StrategyConfig(
            name="rsi_momentum_regime_v1", enabled=True, market=MarketConfig(timeframe="4h")
        )
    )
    f = pd.DataFrame(
        {
            "ready": [True] * 4,
            "close": [100 + side] * 4,
            "ema": [100] * 4,
            "adx": [30, 30, 25, 30],
            "rsi": [50 + side * 10, 50 - side * 20, 50 + side * 10, 50],
        }
    )
    assert s._entries(f, side).tolist() == [True, False, False, False]
    assert s._exits(f, side).tolist() == [False, True, False, True]
