"""Causality and independent signal-rule regressions for each architecture."""

import numpy as np
import pandas as pd
import pytest

from quant_lab.mtf_execution import FAMILIES, configuration, prepare
from quant_lab.mtf_features import (
    STEPS,
    base_setup,
    closed_features,
    confirmation,
    features,
    trigger,
)
from quant_lab.strategies.registry import StrategyRegistry


def candles(n=3600, tf="15m"):
    idx = pd.date_range("2020-01-01", periods=n, freq=STEPS[tf], tz="UTC")
    t = np.arange(n)
    close = 100 + np.sin(t / 15) * 5 + t * 0.007
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.6,
            "low": close - 0.6,
            "close": close,
            "volume": 1.0,
        },
        index=idx,
    )


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("version", ["V1", "V2", "V3", "V4"])
def test_all_architectures_prefix_invariance(family, version):
    config = configuration("BTCUSDT", family, version, "LONG_SHORT")
    strategy = StrategyRegistry().discover().create(config)
    f = candles(tf=config.market.timeframe)
    full = strategy.prepare_features(f)
    for n in (1, 17, 839, 3211):
        partial = strategy.prepare_features(f.iloc[:n])
        pd.testing.assert_frame_equal(partial, full.iloc[:n])
    for suffix in ("1h", "4h"):
        column = "available_at_" + suffix
        if column in full:
            known = full[column].dropna()
            assert (known <= known.index + STEPS[config.market.timeframe]).all()


def test_closed_hour_and_four_hour_exact_boundary():
    f = candles(32)
    hourly = closed_features(f, "15m", "1h")
    assert hourly.close.iloc[:3].isna().all()
    assert hourly.close.iloc[3] == f.close.iloc[3]
    assert hourly.close.iloc[4:7].eq(f.close.iloc[3]).all()
    higher = closed_features(f, "15m", "4h")
    assert higher.close.iloc[:15].isna().all()
    assert higher.close.iloc[15] == f.close.iloc[15]
    missing = closed_features(f.drop(f.index[2]), "15m", "4h")
    assert missing.close.iloc[:-1].isna().all()


def test_channel_excludes_current_and_pullback_excludes_same_bar():
    f = candles(250, "1h")
    values = features(f)
    assert values.channel_high.iloc[-1] == f.high.iloc[-21:-1].max()
    for side in ("long", "short"):
        assert values[f"{side}_ema_touch_age"].dropna().between(1, 3).all()
    changed = f.copy()
    changed.iloc[-1, changed.columns.get_loc("high")] = 1000
    assert features(changed).channel_high.iloc[-1] == values.channel_high.iloc[-1]


@pytest.mark.parametrize("side,sign", [("long", 1), ("short", -1)])
def test_thresholds_and_architecture_rules(side, sign):
    # One independent favorable setup, then isolate each strict rule.
    f = pd.DataFrame(
        {
            "close": [100 + 10 * sign],
            "ema20": [100.0],
            "ema50": [100 - sign],
            "ema200": [100 - 2 * sign],
            "rsi": [50 + sign],
            "adx": [26.0],
            "plus_di": [20 + sign],
            "minus_di": [20 - sign],
            "middle": [100.0],
            "middle_slope": [sign],
            "width_expanding": [True],
            "ema50_slope": [sign],
            "previous_high": [101.0],
            "previous_low": [99.0],
            "channel_high": [105.0],
            "channel_low": [95.0],
            "upper_cross": [sign == 1],
            "lower_cross": [sign == -1],
            "consolidation": [True],
            f"{side}_ema_touch_age": [1.0],
            f"{side}_middle_touch_age": [1.0],
        }
    )
    for family in FAMILIES:
        assert base_setup(f, family, side).iloc[0]
        for version in ("V1", "V2", "V3", "V4"):
            assert trigger(f, family, side, version).iloc[0]
        for version in ("V3", "V4"):
            assert confirmation(f, family, side, version).iloc[0]
    f.adx = 25
    assert not base_setup(f, "ema_adx", side).iloc[0]
    f[f"{side}_ema_touch_age"] = np.nan
    assert not trigger(f, "trend_pullback", side, "V1").iloc[0]
    assert trigger(f, "trend_pullback", side, "V3").iloc[0]
    assert not trigger(f, "ema_adx", side, "V4").iloc[0]


def test_prepared_decisions_are_shifted_by_availability_not_values():
    f = candles(1000, "1h")
    data = {
        "frames": {"1h": f},
        "mark": f,
        "funding": pd.DataFrame({"rate": []}, index=pd.DatetimeIndex([], tz="UTC")),
    }
    config = configuration("BTCUSDT", "donchian", "V1")
    source, _, _, decisions, feat = prepare(data, config)[0]
    assert decisions.index.equals(source.index + STEPS["1h"])
    np.testing.assert_allclose(decisions.distance, feat.risk_atr * 2, equal_nan=True)
    assert decisions["le"].tolist() == feat.long_final.tolist()
