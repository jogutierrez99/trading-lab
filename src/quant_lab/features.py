"""Close-available rolling features. Warmup stays NaN; no future filling."""

import pandas as pd


def ema(close: pd.Series, period: int) -> pd.Series:
    """Recursive EMA seeded at the first observation, hidden until period samples."""
    if type(period) is not int or period < 1:
        raise ValueError("period must be a positive integer")
    return close.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI, seeded by the arithmetic mean of the first period differences."""
    if type(period) is not int or period < 1:
        raise ValueError("period must be a positive integer")
    delta = close.diff()
    gains, losses = delta.clip(lower=0), -delta.clip(upper=0)
    for series in (gains, losses):
        if len(series) > period:
            series.iloc[period] = series.iloc[1 : period + 1].mean()
        series.iloc[:period] = float("nan")
    up = gains.ewm(alpha=1 / period, adjust=False, min_periods=1).mean()
    down = losses.ewm(alpha=1 / period, adjust=False, min_periods=1).mean()
    result = 100 - 100 / (1 + up / down)
    return result.mask((up == 0) & (down == 0), 50.0)


def sma(close: pd.Series, period: int) -> pd.Series:
    if type(period) is not int or period < 1:
        raise ValueError("period must be a positive integer")
    return close.rolling(period, min_periods=period).mean()


def true_range(candles: pd.DataFrame) -> pd.Series:
    previous = candles["close"].shift(1)
    ranges = pd.concat(
        [
            candles.high - candles.low,
            (candles.high - previous).abs(),
            (candles.low - previous).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1, skipna=False)


def atr(candles: pd.DataFrame, period: int = 14) -> pd.Series:
    """Arithmetic mean of TR, not Wilder smoothing; first TR needs previous close."""
    return sma(true_range(candles), period)


def baseline_features(candles: pd.DataFrame) -> pd.DataFrame:
    result = candles.copy()
    result["sma_50"] = sma(candles.close, 50)
    result["sma_200"] = sma(candles.close, 200)
    result["atr_14"] = atr(candles, 14)
    return result
