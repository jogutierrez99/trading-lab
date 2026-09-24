"""Explicit temporal translations; original strategy signal methods stay frozen."""

import numpy as np

from quant_lab.features import atr, ema, rsi
from quant_lab.strategies.base import Signals
from quant_lab.study_data import HOURS, days_to_bars, hours_to_bars
from quant_lab.study_states import channel_retest, rsi_reset


def unsupported(name, timeframe):
    if name == "mtf_momentum" and timeframe != "1h":
        return "Fixed 4h confirmation is no longer a higher timeframe; hypothesis not changed."
    if name == "trend_acceleration" and timeframe == "1d":
        return "Frozen 12h slope cannot be exactly represented on daily candles."
    return None


def prepare(strategy, frame, timeframe):
    name, p = strategy.name, strategy.parameters
    if unsupported(name, timeframe):
        raise ValueError(unsupported(name, timeframe))
    # The source config is retained verbatim. It constructs the original feature baseline;
    # every time-valued column is explicitly replaced below before any signal is evaluated.
    f = strategy.prepare_features(frame)

    def h(hours):
        return hours_to_bars(hours, timeframe)

    def d(days):
        return days_to_bars(days, timeframe)

    if name == "time_series_momentum":
        f["momentum"] = f.close.shift(1) / f.close.shift(d(p.lookback_days) + 1) - 1
    if name == "vol_momentum":
        f["momentum"] = f.close / f.close.shift(d(p.lookback_days)) - 1
        f["volatility"] = volatility(f.close, h(strategy.config.risk.volatility_period), timeframe)
    if name == "bb_squeeze":
        f["threshold"] = (
            f.bandwidth.shift(1).rolling(d(30)).quantile(p.squeeze_percentile_pct / 100)
        )
        f["squeeze"] = (f.bandwidth < f.threshold).astype(float).where(f.threshold.notna())
        f["recent_squeeze"] = f["squeeze"].shift(1).rolling(h(24)).max()
    if name in {"atr_breakout", "low_vol_pullback", "regime_trend", "vol_expansion_trend"}:
        percentile = {"atr_breakout": 0.6, "regime_trend": 0.4}.get(name)
        if percentile is None:
            percentile = p.percentile_pct / 100
        f["threshold"] = f.atr_ratio.shift(1).rolling(d(30)).quantile(percentile)
    if name == "low_vol_pullback":
        f["exit_threshold"] = f.atr_ratio.shift(1).rolling(d(30)).quantile(0.7)
    if name in {"trend_strength", "dual_momentum"}:
        f["roc_short"] = f.close / f.close.shift(d(p.short_days)) - 1
        f["roc_long"] = f.close / f.close.shift(d(p.long_days)) - 1
    if name == "trend_strength":
        f["ema50_prior"] = f.ema50.shift(h(24))
        f["prior_high"] = f.high.shift(1).rolling(h(48)).max()
    if name in {"regime_trend", "rsi_momentum_reset"}:
        f["roc30"] = f.close / f.close.shift(d(30)) - 1
    if name == "regime_trend":
        f["prior_high"] = f.high.shift(1).rolling(h(48)).max()
    if name in {"vol_expansion_trend", "vol_contraction_expansion"}:
        f["roc7"] = f.close / f.close.shift(d(7)) - 1
        f["prior_high"] = f.high.shift(1).rolling(h(24)).max()
    if name == "vol_expansion_trend":
        f["ratio_sma24"] = f.atr_ratio.rolling(h(24)).mean()
    if name == "trend_acceleration":
        f["slope_fast"] = f.ema50 / f.ema50.shift(h(p.fast_hours)) - 1
        f["slope_slow"] = f.ema200 / f.ema200.shift(h(72)) - 1
        f["previous_slope_fast"] = f.slope_fast.shift(h(24))
        f["prior_high"] = f.high.shift(1).rolling(h(24)).max()
    if name == "channel_break_retest":
        f["prior_high"] = f.high.shift(1).rolling(h(p.channel_hours)).max()
        states = channel_retest(f)  # Explicit original retest expiry: 24 candles.
        f[states.columns] = states
    if name == "rsi_momentum_reset":
        states = rsi_reset(f, p.reset_threshold, h(48))
        f[states.columns] = states
    if name == "vol_contraction_expansion":
        past = f.atr_ratio.shift(1).rolling(d(30))
        f["p30"], f["p50"] = past.quantile(0.3), past.quantile(0.5)
        f["contraction"] = (f.atr_ratio < f.p30).astype(float).where(f.p30.notna())
        f["recent_contractions"] = f.contraction.shift(1).rolling(24).sum()
    return f


def signals(strategy, features):
    return Signals(
        tuple(strategy.generate_long_entries(features)),
        tuple(strategy.generate_long_exits(features)),
        (False,) * len(features),
        (False,) * len(features),
    )


def volatility(close, period, timeframe):
    return close.pct_change(fill_method=None).rolling(period).std(ddof=1) * np.sqrt(
        365 * 24 / HOURS[timeframe]
    )


def regimes(frame, timeframe):
    f = frame.copy()
    f["ema50"], f["ema200"] = ema(f.close, 50), ema(f.close, 200)
    f["atr"] = atr(f, 14)
    f["rsi"] = rsi(f.close, 14)
    f["trend"] = "UNKNOWN"
    f.loc[f.ema50 > f.ema200, "trend"] = "BULL"
    f.loc[f.ema50 < f.ema200, "trend"] = "BEAR"
    f.loc[(f.ema50 / f.ema200 - 1).abs() <= 0.0025, "trend"] = "SIDEWAYS"
    ratio = f.atr / f.close
    past = ratio.shift(1).rolling(days_to_bars(30, timeframe))
    low, high = past.quantile(0.3), past.quantile(0.7)
    f["volatility_regime"] = "UNKNOWN"
    f.loc[high.notna(), "volatility_regime"] = "NORMAL_VOL"
    f.loc[ratio < low, "volatility_regime"] = "LOW_VOL"
    f.loc[ratio > high, "volatility_regime"] = "HIGH_VOL"
    return f[["trend", "volatility_regime"]]
