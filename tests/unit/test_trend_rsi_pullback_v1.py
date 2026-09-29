"""Signals, strict parameters and completed-hour prefix invariance."""

import numpy as np
import pandas as pd
import pytest

from quant_lab.config import MarketConfig, StrategyConfig
from quant_lab.strategies.registry import StrategyRegistry
from quant_lab.strategies.trend_rsi_pullback_v1 import Parameters


def strategy(**parameters):
    return (
        StrategyRegistry()
        .discover()
        .create(
            StrategyConfig(
                name="trend_rsi_pullback_v1",
                enabled=True,
                market=MarketConfig(timeframe="15m"),
                parameters=parameters,
            )
        )
    )


def candles(short=False, n=1400):
    price = 100 + np.arange(n) * 0.1
    price[-10:] -= np.arange(10) * 0.7
    if short:
        price = 500 - price
    return pd.DataFrame(
        {"open": price, "high": price + 0.2, "low": price - 0.2, "close": price, "volume": 10.0},
        index=pd.date_range("2022-01-01", periods=n, freq="15min", tz="UTC"),
    )


@pytest.mark.parametrize("variant", ["V1", "V2", "V3"])
@pytest.mark.parametrize("short", [False, True])
def test_long_short_and_warmup(variant, short):
    s = strategy(variant=variant)
    signals = s.generate_signals(candles(short))
    expected = signals.short_entries if short else signals.long_entries
    opposite = signals.long_entries if short else signals.short_entries
    assert any(expected[-10:]) and not any(opposite)
    assert not any(expected[:999])
    assert not any(signals.long_exits) and not any(signals.short_exits)


@pytest.mark.parametrize("variant", ["V1", "V2", "V3"])
def test_features_and_signals_prefix_invariant(variant):
    s, frame = strategy(variant=variant), candles()
    full = s.prepare_features(frame)
    signals = s.generate_signals(frame)
    for end in (0, 2, 999, 1000, 1001, 1003, 1199, 1394, 1399):
        part = s.prepare_features(frame.iloc[:end])
        pd.testing.assert_frame_equal(part, full.iloc[:end], check_freq=False)
        prefix = s.generate_signals(frame.iloc[:end])
        for field in ("long_entries", "short_entries", "long_exits", "short_exits"):
            assert getattr(prefix, field) == getattr(signals, field)[:end]


def test_hour_available_only_on_final_quarter_and_slope_uses_past():
    frame = candles()
    s = strategy(variant="V3")
    f = s.prepare_features(frame)
    assert f.trend_close.iloc[:3].isna().all()
    assert f.trend_close.iloc[3] == frame.close.iloc[3]
    assert f.trend_close.iloc[4:7].eq(frame.close.iloc[3]).all()
    assert (
        f.available_at.dropna()
        <= (f.index.to_series() + pd.Timedelta(minutes=15)).loc[f.available_at.notna()]
    ).all()
    hourly = frame.close.iloc[3::4]
    means = hourly.rolling(185).mean()
    assert f.trend_slope.iloc[1399] == pytest.approx(means.iloc[-1] - means.iloc[-6])
    changed = frame.copy()
    changed.iloc[1399, changed.columns.get_loc("close")] += 999
    pd.testing.assert_frame_equal(s.prepare_features(changed).iloc[:1399], f.iloc[:1399])


def test_gap_restarts_indicators_and_warmup():
    s = strategy(variant="V3")
    frame = candles().drop(candles().index[1001])
    f = s.prepare_features(frame)
    assert f.rsi.iloc[1001:1003].isna().all()
    assert not f.ready.iloc[1001:].any()
    with pytest.raises(ValueError, match="sorted"):
        s.prepare_features(frame.iloc[::-1])


def test_strict_thresholds_and_slope_filters():
    f = pd.DataFrame(
        {
            "ready": [True] * 5,
            "rsi": [29.0, 30.0, 71.0, 70.0, 29.0],
            "trend_close": [101.0, 101.0, 99.0, 99.0, 101.0],
            "trend_sma": [100.0] * 5,
            "trend_slope": [1.0, 1.0, -1.0, -1.0, -1.0],
        }
    )
    assert strategy().generate_long_entries(f) == [True, False, False, False, True]
    assert strategy().generate_short_entries(f) == [False, False, True, False, False]
    assert strategy(variant="V3").generate_long_entries(f) == [True, False, False, False, False]
    assert strategy(variant="V3").generate_short_entries(f) == [False, False, True, False, False]
    f["rsi"] = 50.0
    assert not any(strategy().generate_long_entries(f))
    assert not any(strategy().generate_short_entries(f))


@pytest.mark.parametrize("oversold", [25, 30, 35])
def test_mirror(oversold):
    assert Parameters(rsi_oversold=oversold).rsi_overbought == 100 - oversold


@pytest.mark.parametrize(
    "parameters",
    [
        {"sma_length": 0},
        {"sma_length": "185"},
        {"rsi_length": True},
        {"rsi_oversold": 50},
        {"rsi_oversold": 25, "rsi_overbought": 70},
        {"atr_multiplier": float("nan")},
        {"atr_length": 0},
        {"reward_risk": -1.0},
        {"sma_slope_lookback": 4},
        {"variant": "V4"},
        {"unknown": 1},
    ],
)
def test_invalid_parameters(parameters):
    with pytest.raises(ValueError):
        strategy(**parameters)


def test_registry_preserves_existing_strategies_and_declares_capabilities():
    registry = StrategyRegistry().discover()
    assert "trend_following" in registry.names() and "mtf_ema_adx" in registry.names()
    row = next(r for r in registry.catalogue() if r["strategy_id"] == "trend_rsi_pullback_v1")
    assert row["timeframes"] == ("15m",)
    assert row["modes"] == ("LONG_ONLY", "SHORT_ONLY", "LONG_SHORT")
    assert row["execution"] == "ohlcv"
