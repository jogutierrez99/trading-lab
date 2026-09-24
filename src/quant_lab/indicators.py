"""Additional causal OHLCV features. Existing Batch 001 formulas remain unchanged."""

import numpy as np
import pandas as pd

from quant_lab.features import sma, true_range


def wilder(values: pd.Series, period: int) -> pd.Series:
    """Arithmetic seed of the first complete window, then Wilder recursion."""
    if type(period) is not int or period < 1:
        raise ValueError("period must be a positive integer")
    seeds = values.rolling(period, min_periods=period).mean()
    positions = np.flatnonzero(seeds.notna().to_numpy())
    if not len(positions):
        return pd.Series(float("nan"), index=values.index)
    first = int(positions[0])
    seeded = values.copy()
    seeded.iloc[:first] = float("nan")
    seeded.iloc[first] = seeds.iloc[first]
    return seeded.ewm(alpha=1 / period, adjust=False, min_periods=1).mean()


def adx(candles: pd.DataFrame, period: int = 14) -> pd.Series:
    up = candles.high.diff()
    down = -candles.low.diff()
    plus = up.where((up > down) & (up > 0), 0.0).where(up.notna())
    minus = down.where((down > up) & (down > 0), 0.0).where(down.notna())
    smoothed_tr = wilder(true_range(candles), period)
    plus_di = (100 * wilder(plus, period) / smoothed_tr).mask(smoothed_tr == 0, 0.0)
    minus_di = (100 * wilder(minus, period) / smoothed_tr).mask(smoothed_tr == 0, 0.0)
    total = plus_di + minus_di
    dx = (100 * (plus_di - minus_di).abs() / total).mask(total == 0, 0.0)
    return wilder(dx, period)


def bollinger(close: pd.Series, period: int = 20, width: float = 2.0) -> pd.DataFrame:
    middle = sma(close, period)
    deviation = close.rolling(period).std(ddof=0) * width
    return pd.DataFrame(
        {
            "middle": middle,
            "upper": middle + deviation,
            "lower": middle - deviation,
            "bandwidth": 2 * deviation / middle,
        }
    )


def realized_volatility(close: pd.Series, period: int = 720) -> pd.Series:
    """Sample standard deviation of simple hourly returns, annualized sqrt(8760)."""
    if type(period) is not int or period < 2:
        raise ValueError("period must be an integer >= 2")
    return close.pct_change(fill_method=None).rolling(period).std(ddof=1) * np.sqrt(24 * 365)


def volatility_fractions(
    close: pd.Series, period: int, target_pct: float, minimum_pct: float, maximum_pct: float
) -> pd.Series:
    vol = realized_volatility(close, period)
    result = (target_pct / 100 / vol).clip(minimum_pct / 100, maximum_pct / 100)
    return result.where(np.isfinite(vol) & (vol > 0))
