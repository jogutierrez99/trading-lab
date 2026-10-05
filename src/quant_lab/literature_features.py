"""Shared causal preparation for the literature hypotheses; no execution."""

from abc import abstractmethod

import pandas as pd

from quant_lab.config import StrictModel
from quant_lab.features import atr, ema, rsi
from quant_lab.indicators import adx
from quant_lab.strategies.base import BaseStrategy
from quant_lab.study_data import HOURS
from quant_lab.study_execution import continuous_blocks


class LiteratureStrategy(BaseStrategy[StrictModel]):
    """Shared plumbing only; the four hypotheses remain separate concrete strategies."""

    version = "1.0.0"
    status = "research"
    created_at = "2026-10-04T00:00:00+00:00"
    lab_extended_metrics = True
    lab_entry_diagnostics = True

    @classmethod
    def check_timeframe(cls, timeframe):
        if timeframe not in cls.lab_timeframes:
            raise ValueError(f"{cls.name} requires {cls.lab_timeframes}")

    def prepare_features(self, candles):
        self.required_warmup(self.parameters.model_dump(), self.config.market.timeframe)
        return segmented(candles, self.config.market.timeframe, self._features)

    @abstractmethod
    def _features(self, candles): ...

    @abstractmethod
    def _entries(self, features, side): ...

    @abstractmethod
    def _exits(self, features, side): ...

    def generate_long_entries(self, f):
        return self._entries(f, 1).fillna(False).tolist()

    def generate_short_entries(self, f):
        return self._entries(f, -1).fillna(False).tolist()

    def generate_long_exits(self, f):
        return self._exits(f, 1).fillna(False).tolist()

    def generate_short_exits(self, f):
        return self._exits(f, -1).fillna(False).tolist()


def segmented(candles, timeframe, calculator):
    index = candles.index
    step = pd.Timedelta(hours=HOURS[timeframe])
    if (
        not isinstance(index, pd.DatetimeIndex)
        or str(index.tz) != "UTC"
        or not index.is_unique
        or not index.is_monotonic_increasing
        or index.hasnans
        or (index != index.floor(step)).any()
    ):
        raise ValueError("Require sorted unique aligned UTC candles")
    if candles.empty:
        return calculator(candles)
    return pd.concat([calculator(block) for block in continuous_blocks(candles, timeframe)])


def trend_features(candles, parameters, with_rsi=False):
    p = parameters
    f = candles.copy()
    f["ema"] = ema(f.close, p.ema_period)
    f["ema_slope"] = f.ema - f.ema.shift(3)
    f["adx"] = adx(f, p.adx_period)
    f["atr"] = atr(f, p.atr_period)
    if with_rsi:
        f["rsi"] = rsi(f.close, p.rsi_period)
    f["ready"] = (
        (pd.Series(range(1, len(f) + 1), index=f.index) >= 5 * p.ema_period)
        & f[["ema", "ema_slope", "adx", "atr"]].notna().all(axis=1)
        & (f.atr > 0)
    )
    return f
