"""Reusable causal features and closed-candle alignment for the MTF research series."""

import pandas as pd

from quant_lab.features import atr, ema, rsi, true_range
from quant_lab.indicators import adx, bollinger, wilder

STEPS = {"15m": pd.Timedelta(minutes=15), "1h": pd.Timedelta(hours=1), "4h": pd.Timedelta(hours=4)}


def features(candles: pd.DataFrame) -> pd.DataFrame:
    f = candles.copy().join(bollinger(candles.close, 20, 2.0))
    for n in (20, 50, 200):
        f[f"ema{n}"] = ema(f.close, n)
    f["rsi"] = rsi(f.close, 14)
    f["adx"] = adx(f, 14)
    f["atr"] = atr(f, 14)
    up, down = f.high.diff(), -f.low.diff()
    tr = wilder(true_range(f), 14)
    for name, movement, other in (("plus_di", up, down), ("minus_di", down, up)):
        dm = movement.where((movement > other) & (movement > 0), 0.0).where(movement.notna())
        f[name] = (100 * wilder(dm, 14) / tr).mask(tr == 0, 0.0)
    f["channel_high"] = f.high.shift(1).rolling(20).max()
    f["channel_low"] = f.low.shift(1).rolling(20).min()
    f["previous_high"], f["previous_low"] = f.high.shift(1), f.low.shift(1)
    f["middle_slope"] = f.middle.diff()
    f["ema50_slope"] = f.ema50.diff()
    f["width_expanding"] = f.bandwidth >= f.bandwidth.shift(1)
    f["upper_cross"] = (f.close > f.upper) & (f.close.shift(1) <= f.upper.shift(1))
    f["lower_cross"] = (f.close < f.lower) & (f.close.shift(1) >= f.lower.shift(1))
    for side, sign in (("long", 1), ("short", -1)):
        for name, lines in (("ema", ["ema20", "ema50"]), ("middle", ["middle"])):
            touch = pd.Series(False, index=f.index)
            for line in lines:
                touch |= (
                    (f.low <= f[line])
                    & (f.high >= f[line])
                    & ((f.close.shift(1) - f[line].shift(1)) * sign > 0)
                )
            age = pd.Series(float("nan"), index=f.index)
            for lag in (3, 2, 1):
                age = age.mask(touch.shift(lag, fill_value=False), float(lag))
            f[f"{side}_{name}_touch_age"] = age
    f["consolidation"] = (
        f.high.shift(1).rolling(3).max() - f.low.shift(1).rolling(3).min()
    ) <= 2 * f.atr.shift(1)
    return f


def complete_bars(frame: pd.DataFrame, source_tf: str, target_tf: str) -> pd.DataFrame:
    required = int(STEPS[target_tf] / STEPS[source_tf])
    grouped = frame.resample(target_tf, label="left", closed="left", origin="epoch")
    result = grouped.agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return result.loc[grouped.size() == required]


def closed_features(
    frame: pd.DataFrame, source_tf: str, target_tf: str, calculator=features
) -> pd.DataFrame:
    higher = calculator(complete_bars(frame, source_tf, target_tf))
    higher.index = higher.index + STEPS[target_tf]
    higher["available_at"] = higher.index
    aligned = higher.reindex(frame.index + STEPS[source_tf], method="ffill")
    aligned.index = frame.index
    return aligned


def regime(f: pd.DataFrame, family: str, side: str) -> pd.Series:
    sign = 1 if side == "long" else -1
    if family == "bollinger":
        return ((f.close - f.middle) * sign > 0) & (f.middle_slope * sign > 0)
    return (f.ema50 - f.ema200) * sign > 0


def base_setup(f: pd.DataFrame, family: str, side: str) -> pd.Series:
    sign = 1 if side == "long" else -1
    if family == "trend_pullback":
        return (
            regime(f, family, side) & ((f.close - f.ema50) * sign > 0) & ((f.rsi - 50) * sign > 0)
        )
    if family == "bollinger":
        return regime(f, family, side) & f.width_expanding
    if family == "donchian":
        return ((f.close - f.ema50) * sign > 0) & (f.ema50_slope * sign > 0)
    if family == "ema_adx":
        return regime(f, family, side) & (f.adx > 25) & ((f.plus_di - f.minus_di) * sign > 0)
    raise ValueError("Unknown family")


def trigger(f: pd.DataFrame, family: str, side: str, version: str) -> pd.Series:
    sign = 1 if side == "long" else -1
    previous = f.previous_high if sign == 1 else f.previous_low
    channel = f.channel_high if sign == 1 else f.channel_low
    recovery = (f.close - previous) * sign > 0
    pull = f[f"{side}_ema_touch_age"].notna() & ((f.close - f.ema20) * sign > 0) & recovery
    middle_pull = (
        f[f"{side}_middle_touch_age"].notna() & ((f.close - f.middle) * sign > 0) & recovery
    )
    breakout = (f.close - channel) * sign > 0
    cross = f.upper_cross if sign == 1 else f.lower_cross
    if family == "trend_pullback":
        return ((f.ema20 - f.ema50) * sign > 0) & recovery if version == "V3" else pull
    if family == "bollinger":
        if version == "V3":
            return ((f.close - f.middle) * sign > 0) & cross
        return middle_pull if version == "V4" else cross | middle_pull
    if family == "donchian":
        return breakout & (f.consolidation | pull) if version == "V4" else breakout
    if family == "ema_adx":
        if version == "V3":
            return ((f.ema20 - f.ema50) * sign > 0) & breakout
        return breakout & pull if version == "V4" else breakout
    raise ValueError("Unknown family")


def confirmation(f: pd.DataFrame, family: str, side: str, version: str) -> pd.Series:
    sign = 1 if side == "long" else -1
    if family == "trend_pullback":
        trend = (
            (f.ema50 - f.ema200) * sign > 0 if version == "V3" else (f.close - f.ema50) * sign > 0
        )
        return trend & ((f.rsi - 50) * sign > 0)
    if family == "bollinger":
        valid = ((f.close - f.middle) * sign > 0) & f.width_expanding
        return valid if version == "V3" else valid & (f.middle_slope * sign > 0)
    if family == "donchian":
        width = f.channel_high - f.channel_low
        rank = (f.close - f.channel_low) / width
        return (width > 0) & ((rank >= 0.8) if sign == 1 else (rank <= 0.2))
    return (f.adx > 25) & ((f.plus_di - f.minus_di) * sign > 0)
