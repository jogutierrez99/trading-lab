"""Shared causal and parameter contracts for the two independent hypotheses."""

import numpy as np
import pandas as pd
import pytest

from quant_lab.config import MarketConfig, StrategyConfig
from quant_lab.strategies.registry import StrategyRegistry

NAMES = ("volatility_breakout_intraday_v1", "range_mean_reversion_v1")


def strategy(name, **params):
    return (
        StrategyRegistry()
        .discover()
        .create(
            StrategyConfig(
                name=name, enabled=True, market=MarketConfig(timeframe="15m"), parameters=params
            )
        )
    )


def candles(n=2400):
    price = 100 + np.arange(n) * 0.01 + np.sin(np.arange(n) / 7)
    return pd.DataFrame(
        {"open": price, "high": price + 0.2, "low": price - 0.2, "close": price, "volume": 10.0},
        index=pd.date_range("2022-01-01", periods=n, freq="15min", tz="UTC"),
    )


@pytest.mark.parametrize("name", NAMES)
def test_prefix_future_mutation_hour_boundaries_and_warmup(name):
    s, frame = strategy(name), candles()
    full = s.prepare_features(frame)
    assert s.required_warmup({}, "15m") == 2004
    assert not full.ready.iloc[:1999].any()
    assert full.ready.iloc[2000]
    for n in (0, 1, 3, 4, 7, 8, 40, 1999, 2000, 2001, 2100, 2399):
        pd.testing.assert_frame_equal(s.prepare_features(frame.iloc[:n]), full.iloc[:n])
    changed = frame.copy()
    changed.iloc[2200:, :4] *= 3
    pd.testing.assert_frame_equal(s.prepare_features(changed).iloc[:2200], full.iloc[:2200])
    # Quarter 00:30 cannot see 00:45; at its close 01:00 the full hour is available.
    assert pd.isna(full.hour_close.iloc[2])
    assert full.hour_close.iloc[3] == frame.close.iloc[3]
    newer = frame.copy()
    newer.iloc[3, newer.columns.get_loc("close")] += 5
    modified = s.prepare_features(newer)
    pd.testing.assert_frame_equal(modified.iloc[:3], full.iloc[:3])
    assert modified.hour_close.iloc[3] != full.hour_close.iloc[3]


@pytest.mark.parametrize("name", NAMES)
def test_gap_resets_all_features_and_no_partial_hour_leaks(name):
    s, frame = strategy(name), candles()
    gapped = frame.drop(frame.index[1700])
    f = s.prepare_features(gapped)
    tail = frame.iloc[1701:]
    pd.testing.assert_frame_equal(f.loc[tail.index], s.prepare_features(tail), check_freq=False)
    assert not f.loc[tail.index].ready.any()
    assert (
        f.available_at.dropna().le(f.available_at.dropna().index + pd.Timedelta(minutes=15)).all()
    )


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("params", [{"ema_period": True}, {"atr_period": 1}, {"unknown": 3}])
def test_strict_invalid_parameters(name, params):
    with pytest.raises(ValueError):
        strategy(name, **params)


@pytest.mark.parametrize("name", NAMES)
def test_timeframe_alignment_and_dynamic_warmup(name):
    s = strategy(name, ema_period=200)
    assert s.required_warmup(s.parameters.model_dump(), "15m") == 4004
    with pytest.raises(ValueError):
        s.required_warmup({}, "1h")
    with pytest.raises(ValueError):
        s.prepare_features(candles().iloc[::-1])
    bad = candles()
    bad.index += pd.Timedelta(minutes=1)
    with pytest.raises(ValueError):
        s.prepare_features(bad)
