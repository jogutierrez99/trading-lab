"""Rule regressions and prefix invariance across the frozen matrix."""

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from quant_lab.batch_006_execution import MODES, configuration
from quant_lab.strategies.bollinger_regime_reversal import (
    VARIANTS,
    BollingerRegimeReversalStrategy,
    Parameters,
)


def candles(n=450):
    close = 100 + np.random.default_rng(42).normal(0, 1, n).cumsum()
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 100.0},
        index=pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC"),
    )


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("mode", MODES)
def test_causal_features_and_signals(variant, mode):
    s = BollingerRegimeReversalStrategy(configuration("BTCUSDT", "1h", variant, mode))
    source = candles()
    full = s.prepare_features(source)
    signals = s.generate_signals(source)
    for length in (199, 200, 237, 371):
        pd.testing.assert_frame_equal(s.prepare_features(source.iloc[:length]), full.iloc[:length])
        partial = s.generate_signals(source.iloc[:length])
        for field in ("long_entries", "short_entries", "long_exits", "short_exits"):
            assert getattr(partial, field) == getattr(signals, field)[:length]
    assert not any(signals.long_entries[:199])
    assert not any(signals.short_entries[:199])
    if mode == "LONG_ONLY":
        assert not any(signals.short_entries)
    if mode == "SHORT_ONLY":
        assert not any(signals.long_entries)


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("mode", MODES)
def test_symmetry_and_strict_thresholds(variant, mode):
    s = BollingerRegimeReversalStrategy(configuration("BTCUSDT", "1h", variant, mode))
    p = VARIANTS[variant]
    f = pd.DataFrame(
        {
            "close": [89.0, 111.0],
            "lower": 90.0,
            "upper": 110.0,
            "middle": 100.0,
            "rsi": [p["rsi_long"] - 1, p["rsi_short"] + 1],
            "adx": p["adx"] - 1,
            "distance_ema": 0.079,
        }
    )
    assert s.generate_long_entries(f) == [mode != "SHORT_ONLY", False]
    assert s.generate_short_entries(f) == [False, mode != "LONG_ONLY"]
    assert s.generate_long_exits(f) == [False, True]
    assert s.generate_short_exits(f) == [True, False]
    for field, values in (
        ("rsi", [p["rsi_long"], p["rsi_short"]]),
        ("adx", p["adx"]),
        ("distance_ema", 0.08),
    ):
        blocked = f.copy()
        blocked[field] = values
        assert not any(s.generate_long_entries(blocked))
        assert not any(s.generate_short_entries(blocked))
    f["close"] = [95.0, 105.0]
    f["rsi"] = [55.0, 45.0]
    assert s.generate_long_exits(f) == [True, True]
    assert s.generate_short_exits(f) == [True, True]


def test_indicator_arithmetic_and_strict_parameters():
    source = candles()
    s = BollingerRegimeReversalStrategy(configuration("BTCUSDT", "1h", "A", "LONG_SHORT"))
    f = s.prepare_features(source)
    last = source.close.iloc[-20:]
    assert f.middle.iloc[-1] == pytest.approx(last.mean())
    assert f.upper.iloc[-1] == pytest.approx(last.mean() + 2 * last.std(ddof=0))
    assert f.lower.iloc[-1] == pytest.approx(last.mean() - 2 * last.std(ddof=0))
    assert f.ema200.iloc[-1] == pytest.approx(
        source.close.ewm(span=200, adjust=False).mean().iloc[-1]
    )
    tr = pd.concat(
        [
            source.high - source.low,
            (source.high - source.close.shift()).abs(),
            (source.low - source.close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    assert f.atr.iloc[-1] == pytest.approx(tr.iloc[-14:].mean())
    trend = source.copy()
    trend["open"] = trend["close"] = 100 + np.arange(len(trend), dtype=float)
    trend["high"], trend["low"] = trend.close + 1, trend.close - 1
    f = s.prepare_features(trend)
    assert f.rsi.iloc[-1] == pytest.approx(100.0)
    assert f.adx.iloc[-1] == pytest.approx(100.0)
    for invalid in ({"variant": "D"}, {"trade_mode": "BOTH"}, {"rsi": 12}):
        with pytest.raises(ValidationError):
            Parameters(**invalid)


@pytest.mark.parametrize("tf,bars", [("1h", 72), ("4h", 18), ("1d", 3)])
def test_elapsed_time_stop(tf, bars):
    assert configuration("BTCUSDT", tf, "C", "LONG_SHORT").risk.max_holding_bars == bars
