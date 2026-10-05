import numpy as np
import pandas as pd
import pytest

from quant_lab.config import MarketConfig, StrategyConfig
from quant_lab.indicators import realized_volatility
from quant_lab.lab_funding_adapter import funding_inputs
from quant_lab.mtf_features import complete_bars
from quant_lab.strategies.registry import StrategyRegistry

CASES = [
    ("donchian_trend_v1", "4h"),
    ("risk_managed_momentum_v1", "4h"),
    ("risk_managed_momentum_v1", "1d"),
    ("rsi_momentum_regime_v1", "4h"),
    ("funding_conditional_momentum_v1", "1h"),
]


def candles(tf, n=300):
    idx = pd.date_range("2020-01-01", periods=n, freq=tf, tz="UTC")
    price = 100 + np.sin(np.arange(n) / 5) * 5 + np.arange(n) * 0.01
    return pd.DataFrame(
        {
            "open": price,
            "high": price + 1,
            "low": price - 1,
            "close": price + np.sin(np.arange(n)) * 0.2,
            "volume": 1.0,
        },
        index=idx,
    )


def instance(name, tf):
    cls = StrategyRegistry().discover().implementation(name)
    p = {
        k: v
        for k, v in {
            "ema_period": 10,
            "adx_period": 3,
            "rsi_period": 3,
            "atr_period": 3,
            "momentum_lookback": 12,
            "volatility_period": 12,
            "funding_window": 10,
        }.items()
        if k in cls.parameter_model.model_fields
    }
    return cls(
        StrategyConfig(name=name, enabled=True, market=MarketConfig(timeframe=tf), parameters=p)
    )


def funding(n=40):
    idx = pd.date_range("2020-01-01", periods=n, freq="8h", tz="UTC") + pd.Timedelta(milliseconds=1)
    return pd.DataFrame({"rate": np.sin(np.arange(n)) * 0.001, "interval_hours": 8.0}, index=idx)


@pytest.mark.parametrize("name,tf", CASES)
@pytest.mark.parametrize("cut", [0, 30, 55, 199])
def test_prefix_invariance_of_features_and_signals(name, tf, cut):
    s = instance(name, tf)
    c = candles(tf)
    if name.startswith("funding"):
        c = funding_inputs(c, funding(), s.parameters)
    full = s.prepare_features(c)
    prefix = s.prepare_features(c.iloc[:cut])
    pd.testing.assert_frame_equal(prefix, full.iloc[:cut], check_freq=False)
    signals = s.generate_signals(c)
    short = s.generate_signals(c.iloc[:cut])
    for key in ("long_entries", "short_entries", "long_exits", "short_exits"):
        assert getattr(short, key) == getattr(signals, key)[:cut]


@pytest.mark.parametrize("name,tf", CASES)
def test_gap_resets_features_and_warmup(name, tf):
    s = instance(name, tf)
    c = candles(tf)
    if name.startswith("funding"):
        c = funding_inputs(c, funding(), s.parameters)
    gapped = c.drop(c.index[120:130])
    actual = s.prepare_features(gapped)
    standalone = s.prepare_features(c.iloc[130:])
    pd.testing.assert_frame_equal(actual.loc[standalone.index], standalone, check_freq=False)


@pytest.mark.parametrize("name,tf", CASES)
def test_unknown_parameters_rejected(name, tf):
    cls = StrategyRegistry().discover().implementation(name)
    with pytest.raises(ValueError):
        cls(
            StrategyConfig(
                name=name,
                enabled=True,
                market=MarketConfig(timeframe=tf),
                parameters={"future_data": True},
            )
        )


@pytest.mark.parametrize("tf", ["4h", "1d"])
def test_resampling_uses_complete_closed_bars_only(tf):
    c = candles("15min", 300)
    complete = complete_bars(c, "15m", tf)
    for cut in (1, 16, 95, 96, 200):
        prefix = complete_bars(c.iloc[:cut], "15m", tf)
        expected = complete.loc[
            complete.index + pd.Timedelta(tf) <= c.index[0] + cut * pd.Timedelta(minutes=15)
        ]
        pd.testing.assert_frame_equal(prefix, expected, check_freq=False)


def test_current_bar_not_in_donchian_channel():
    s = instance("donchian_trend_v1", "4h")
    c = candles("4h")
    old = s.prepare_features(c)
    c.iloc[-1, c.columns.get_loc("high")] = 10000
    assert s.prepare_features(c).donchian_high.iloc[-1] == old.donchian_high.iloc[-1]


def test_settlement_offset_and_future_funding_cannot_leak():
    s = instance("funding_conditional_momentum_v1", "1h")
    c = candles("1h", 150)
    f = funding()
    original = funding_inputs(c, f, s.parameters)
    at = c.index[80]
    assert original.loc[at - pd.Timedelta(hours=1), "known_at"] < at
    assert original.loc[at, "known_at"] == at + pd.Timedelta(milliseconds=1)
    prefix = funding_inputs(c.iloc[:80], f.loc[f.index < at], s.parameters)
    pd.testing.assert_frame_equal(prefix, original.iloc[:80], check_freq=False)
    changed = f.copy()
    changed.loc[changed.index >= at, "rate"] = 0.5
    pd.testing.assert_frame_equal(
        funding_inputs(c, changed, s.parameters).iloc[:80], prefix, check_freq=False
    )
    # Current extreme is excluded from its own percentile thresholds.
    assert (
        original.loc[at, "funding_low"]
        == funding_inputs(c, changed, s.parameters).loc[at, "funding_low"]
    )


def test_anualization_is_explicit_and_hourly_formula_unchanged():
    c = candles("4h")
    hourly = realized_volatility(c.close, 20)
    expected = c.close.pct_change(fill_method=None).rolling(20).std(ddof=1) * np.sqrt(8760)
    pd.testing.assert_series_equal(hourly, expected)
    pd.testing.assert_series_equal(realized_volatility(c.close, 20, annual_bars=2190), hourly / 2)
