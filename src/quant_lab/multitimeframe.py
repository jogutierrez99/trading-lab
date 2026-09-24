"""Completed UTC 4h bars and their close-available alignment to hourly decisions."""

import pandas as pd

from quant_lab.features import ema


def completed_4h(candles: pd.DataFrame) -> pd.DataFrame:
    index = candles.index
    if not isinstance(index, pd.DatetimeIndex) or str(index.tz) != "UTC":
        raise ValueError("MTF requires UTC datetime candles")
    if not index.is_unique or not index.is_monotonic_increasing or index.hasnans:
        raise ValueError("MTF timestamps must be unique, sorted and non-null")
    if not index.equals(index.floor("h")) or (
        len(index) > 1 and not (index.to_series().diff().iloc[1:] == pd.Timedelta(hours=1)).all()
    ):
        raise ValueError("MTF requires contiguous aligned hourly candles")
    groups = candles.resample("4h", origin="epoch", closed="left", label="right")
    bars = groups.agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return bars.loc[groups.size() == 4].copy()


def confirmed_4h_features(candles: pd.DataFrame) -> pd.DataFrame:
    bars = completed_4h(candles)
    values = pd.DataFrame(
        {
            "htf_close": bars.close,
            "htf_ema50": ema(bars.close, 50),
            "htf_ema200": ema(bars.close, 200),
            "htf_momentum": bars.close / bars.close.shift(180) - 1,
            "htf_available_at": bars.index,
        },
        index=bars.index,
    )
    # Row 03:00 is a decision at 04:00 and may use the completed 00:00-04:00 bar.
    decision_times = candles.index + pd.Timedelta(hours=1)
    aligned = values.reindex(decision_times, method="ffill")
    aligned.index = candles.index
    return aligned
