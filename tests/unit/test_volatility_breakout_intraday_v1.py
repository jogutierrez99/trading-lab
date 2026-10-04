"""Breakout gates, strict boundaries and prior compression/structure."""

import pandas as pd
import pytest
from test_intraday_contracts import candles, strategy


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize(
    "gate", ["regime", "slope", "compression", "breakout", "expansion", "momentum", "ready"]
)
def test_each_breakout_gate_long_short(side, gate):
    s = strategy("volatility_breakout_intraday_v1")
    f = pd.DataFrame(
        {
            "ready": [True],
            "compressed": [True],
            "hour_close": [100 + side * 10],
            "hour_ema": [100.0],
            "hour_slope": [float(side)],
            "close": [100 + side * 10],
            "breakout_high": [105.0],
            "breakout_low": [95.0],
            "atr_expansion": [1.1],
            "body_atr": [float(side)],
        }
    )
    method = s.generate_long_entries if side == 1 else s.generate_short_entries
    opposite = s.generate_short_entries if side == 1 else s.generate_long_entries
    assert method(f) == [True] and opposite(f) == [False]
    if gate == "regime":
        f["hour_close"] = f.hour_ema
    elif gate == "slope":
        f["hour_slope"] = 0.0
    elif gate == "compression":
        f["compressed"] = False
    elif gate == "breakout":
        f["close"] = f.breakout_high if side == 1 else f.breakout_low
    elif gate == "expansion":
        f["atr_expansion"] = 1.09
    elif gate == "momentum":
        f["body_atr"] = side * 0.49
    else:
        f["ready"] = False
    assert method(f) == [False]


def test_exact_prior_levels_reference_and_current_candle_exclusion():
    s, frame = strategy("volatility_breakout_intraday_v1"), candles()
    f = s.prepare_features(frame)
    assert f.breakout_high.iloc[-1] == frame.high.iloc[-21:-1].max()
    assert f.breakout_low.iloc[-1] == frame.low.iloc[-21:-1].min()
    assert f.atr_reference.iloc[-1] == pytest.approx(f.atr.iloc[-21:-1].mean())
    changed = frame.copy()
    changed.iloc[-1, :4] *= 2
    newer = s.prepare_features(changed)
    for column in (
        "breakout_high",
        "breakout_low",
        "prior_bandwidth",
        "compression_reference",
        "compressed",
        "atr_reference",
    ):
        assert newer[column].iloc[-1] == f[column].iloc[-1]
    assert not any(s.generate_long_exits(f)) and not any(s.generate_short_exits(f))
