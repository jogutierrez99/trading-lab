"""Canonical UTC candles; reject invalid data without sorting or gap filling."""

import numpy as np
import pandas as pd

from quant_lab.history import HistoryRequest

COLUMNS = ["open", "high", "low", "close", "volume"]


def validate_candles(frame: pd.DataFrame, request: HistoryRequest) -> None:
    if list(frame.columns) != COLUMNS:
        raise ValueError(f"Expected columns {COLUMNS}")
    index = frame.index
    if not isinstance(index, pd.DatetimeIndex) or str(index.tz) != "UTC":
        raise ValueError("Candle index must be UTC DatetimeIndex")
    if index.hasnans or not index.is_unique or not index.is_monotonic_increasing:
        raise ValueError("Timestamps must be non-null, unique and sorted")
    expected = pd.date_range(request.download_start, request.end, freq="h", inclusive="left")
    if not index.equals(expected):
        missing = expected.difference(index)
        raise ValueError(
            f"Incomplete or misaligned candles: expected={len(expected)}, actual={len(index)}, "
            f"missing={len(missing)}, first_missing={list(missing[:5])}"
        )
    values = frame.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("OHLCV must be finite")
    if (frame[COLUMNS[:4]] <= 0).any().any() or (frame.volume < 0).any():
        raise ValueError("Prices must be positive and volume nonnegative")
    if (frame.low > frame[["open", "close", "high"]].min(axis=1)).any() or (
        frame.high < frame[["open", "close", "low"]].max(axis=1)
    ).any():
        raise ValueError("Inconsistent OHLC bounds")
