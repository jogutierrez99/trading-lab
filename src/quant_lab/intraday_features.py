"""Closed 1h context and gap resets shared by independent 15m hypotheses."""

import pandas as pd

from quant_lab.features import ema
from quant_lab.indicators import adx
from quant_lab.mtf_features import closed_features


def segmented(candles, calculator):
    if (
        not isinstance(candles.index, pd.DatetimeIndex)
        or str(candles.index.tz) != "UTC"
        or not candles.index.is_monotonic_increasing
        or not candles.index.is_unique
        or (candles.index != candles.index.floor("15min")).any()
    ):
        raise ValueError("Intraday features require sorted unique 15m UTC candles")
    if candles.empty:
        return calculator(candles)
    groups = (candles.index.to_series().diff() != pd.Timedelta(minutes=15)).cumsum()
    return pd.concat([calculator(part) for _, part in candles.groupby(groups)])


def context(candles, ema_period, slope_lookback, adx_period=None):
    def calculate(hourly):
        f = pd.DataFrame(index=hourly.index)
        f["hour_close"] = hourly.close
        f["hour_ema"] = ema(hourly.close, ema_period)
        f["hour_slope"] = f.hour_ema - f.hour_ema.shift(slope_lookback)
        f["hour_slope_pct"] = 100 * f.hour_slope / f.hour_ema.where(f.hour_ema > 0)
        f["hour_count"] = pd.Series(range(1, len(f) + 1), index=f.index, dtype=float)
        if adx_period is not None:
            f["hour_adx"] = adx(hourly, adx_period)
        return f

    return closed_features(candles, "15m", "1h", calculator=calculate)


def context_warmup(ema_period, slope_lookback, adx_period=0):
    # Four extra quarters allow for a partial first clock hour.
    return 4 * max(5 * ema_period, ema_period + slope_lookback, 5 * adx_period) + 4


def ready(f, ema_period, columns):
    return f[columns].notna().all(axis=1) & (f.hour_count >= 5 * ema_period) & (f.atr > 0)
