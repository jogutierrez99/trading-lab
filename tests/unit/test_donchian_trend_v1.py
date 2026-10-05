import pandas as pd
import pytest

from quant_lab.config import MarketConfig, StrategyConfig
from quant_lab.strategies.donchian_trend_v1 import DonchianTrendV1Strategy


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize("gate", [None, "ready", "direction", "slope", "adx", "strength"])
def test_directional_breakout_requires_every_gate(side, gate):
    s = DonchianTrendV1Strategy(
        StrategyConfig(name="donchian_trend_v1", enabled=True, market=MarketConfig(timeframe="4h"))
    )
    f = pd.DataFrame(
        {
            "ready": [True],
            "close": [100 + side],
            "ema": [100],
            "ema_slope": [side],
            "adx": [30],
            "long_strength": [0.2],
            "short_strength": [0.2],
        }
    )
    if gate == "ready":
        f["ready"] = False
    if gate == "direction":
        f["close"] = 100
    if gate == "slope":
        f["ema_slope"] = -side
    if gate == "adx":
        f["adx"] = 25
    if gate == "strength":
        f["long_strength" if side == 1 else "short_strength"] = 0.1
    assert s._entries(f, side).tolist() == [gate is None]
    assert s._exits(f, side).tolist() == [False]
