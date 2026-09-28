"""Frozen additional indicators and events; no changes to legacy MTF formulas."""

import numpy as np
import pandas as pd

from quant_lab.features import atr, true_range
from quant_lab.indicators import wilder
from quant_lab.mtf_features import STEPS, features

FAMILIES = ("supertrend_pullback", "keltner_breakout", "roc_momentum", "volatility_expansion")


def supertrend(frame: pd.DataFrame) -> pd.DataFrame:
    """ATR10 Wilder, multiplier 3; first valid direction seeded bullish."""
    volatility = wilder(true_range(frame), 10).to_numpy()
    close = frame.close.to_numpy()
    midpoint = ((frame.high + frame.low) / 2).to_numpy()
    upper, lower = midpoint + 3 * volatility, midpoint - 3 * volatility
    line = np.full(len(frame), np.nan)
    direction = np.zeros(len(frame), dtype=int)
    for i in range(len(frame)):
        if not np.isfinite(volatility[i]):
            continue
        if i == 0 or direction[i - 1] == 0:
            direction[i] = 1
        else:
            if upper[i] >= upper[i - 1] and close[i - 1] <= upper[i - 1]:
                upper[i] = upper[i - 1]
            if lower[i] <= lower[i - 1] and close[i - 1] >= lower[i - 1]:
                lower[i] = lower[i - 1]
            direction[i] = direction[i - 1]
            if direction[i - 1] == 1 and close[i] < lower[i]:
                direction[i] = -1
            elif direction[i - 1] == -1 and close[i] > upper[i]:
                direction[i] = 1
        line[i] = lower[i] if direction[i] == 1 else upper[i]
    return pd.DataFrame({"st_line": line, "st_direction": direction}, index=frame.index)


def indicators(frame: pd.DataFrame) -> pd.DataFrame:
    f = features(frame).join(supertrend(frame))
    f["kc_middle"] = f.ema20
    f["kc_atr"] = atr(frame, 20)
    f["kc_upper"] = f.kc_middle + 2 * f.kc_atr
    f["kc_lower"] = f.kc_middle - 2 * f.kc_atr
    f["kc_slope"] = f.kc_middle.diff()
    f["kc_event"] = (
        (f.kc_slope > 0) & (f.close > f.kc_upper) & (f.close.shift(1) <= f.kc_upper.shift(1))
    )
    for n in (5, 20):
        f[f"roc{n}"] = 100 * (f.close / f.close.shift(n) - 1)
    f["roc_accelerating"] = f.roc5 > f.roc5.shift(1)
    f["roc_regime"] = (f.roc20 > 0) & (f.roc20 >= f.roc20.shift(1))
    f["roc_event"] = (
        (f.roc20 > 0) & (f.roc5 > f.roc20) & f.roc_accelerating & (f.close > f.channel_high)
    )
    f["width_median"] = f.bandwidth.rolling(100, min_periods=100).median()
    f["compression"] = f.bandwidth < f.width_median
    f["recent_compression"] = f.compression.shift(1).rolling(3, min_periods=3).sum() > 0
    f["expansion_event"] = (
        f.recent_compression & (f.close > f.channel_high) & (f.bandwidth > f.bandwidth.shift(1))
    )
    f["st_trend"] = (f.st_direction == 1) & (f.close > f.st_line)
    touch = (
        ((f.low <= f.st_line) & (f.high >= f.st_line)) | ((f.low <= f.ema20) & (f.high >= f.ema20))
    ) & f.st_trend
    age = pd.Series(np.nan, index=f.index)
    for lag in (3, 2, 1):
        uninterrupted = f.st_trend.rolling(lag + 1).sum() == lag + 1
        age = age.mask(touch.shift(lag, fill_value=False) & uninterrupted, float(lag))
    f["st_touch_age"] = age
    f["st_setup"] = f.st_trend & age.notna()
    f["st_event"] = f.st_setup & (f.close > f.previous_high) & (f.close > f.open)
    f["small_high"] = f.high.shift(1).rolling(3).max()
    f["range_expanding"] = (f.high - f.low > f.atr.shift(1)) & (f.atr > f.atr.shift(1))
    return f


def contiguous_features(frame: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Reset all recursive/rolling indicators after a missing source/aggregate bar."""
    if frame.empty:
        return indicators(frame)
    groups = frame.index.to_series().diff().ne(STEPS[tf]).cumsum()
    return pd.concat([indicators(part) for _, part in frame.groupby(groups)])


def hourly_event(f: pd.DataFrame, family: str) -> pd.Series:
    return f[
        {
            "supertrend_pullback": "st_event",
            "keltner_breakout": "kc_event",
            "roc_momentum": "roc_event",
            "volatility_expansion": "expansion_event",
        }[family]
    ]


def higher_regime(f: pd.DataFrame, family: str) -> pd.Series:
    if family == "supertrend_pullback":
        return f.st_trend
    if family == "keltner_breakout":
        return (f.close > f.kc_middle) & (f.kc_slope > 0)
    if family == "roc_momentum":
        return f.roc_regime
    return f.ema50 > f.ema200


def v4_triggers(f: pd.DataFrame, hourly: pd.DataFrame, allowed: pd.Series, family: str):
    """One trigger per hourly opportunity; 4h TTL; all trigger bars follow the setup."""
    setup = (
        hourly.st_setup
        if family == "supertrend_pullback"
        else hourly.compression
        if family == "volatility_expansion"
        else hourly_event(hourly, family)
    ).eq(True)
    raw = pd.Series(False, index=f.index)
    confirmed = raw.copy()
    final = raw.copy()
    delays = pd.Series(np.nan, index=f.index)
    published = None
    active = None
    touched = None
    for i, time in enumerate(f.index):
        h = hourly.iloc[i]
        available = h.available_at
        if pd.notna(available) and available != published:
            published = available
            if setup.iloc[i]:
                active, touched = available, None
        if not bool(allowed.iloc[i]) or (active is not None and time >= active + STEPS["4h"]):
            active, touched = None, None
        row = f.iloc[i]
        if family in {"supertrend_pullback", "keltner_breakout"}:
            recovery = row.close > row.previous_high and row.close > row.open
            raw.iloc[i] = recovery
            structure = row.close > (h.st_line if family == "supertrend_pullback" else h.kc_middle)
            if not structure:
                active, touched = None, None
            hit = active is not None and time >= active
            if hit and touched is not None and time > touched and recovery:
                confirmed.iloc[i] = True
                delays.iloc[i] = (time - touched).total_seconds() / 3600
            if hit and row.low <= row.ema20 <= row.high:
                touched = time
        else:
            event = row.close > row.small_high and row.close > row.open and row.consolidation
            if family == "volatility_expansion":
                event = event and row.range_expanding
            raw.iloc[i] = bool(event)
            # All three consolidation candles must open after the hourly setup closes.
            confirmed.iloc[i] = bool(
                event and active is not None and time - 3 * STEPS["15m"] >= active
            )
        final.iloc[i] = bool(confirmed.iloc[i] and allowed.iloc[i])
        if final.iloc[i]:
            active, touched = None, None
    return raw, confirmed, final, delays
