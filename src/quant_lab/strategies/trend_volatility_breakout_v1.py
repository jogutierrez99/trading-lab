"""Single-hour EMA trend, previous-channel breakout and ATR expansion at close."""

from typing import Literal

import pandas as pd
from pydantic import Field

from quant_lab.config import StrictModel
from quant_lab.features import atr, ema
from quant_lab.strategies.base import BaseStrategy


class Parameters(StrictModel):
    trend_length: int = Field(default=200, ge=2, le=2000)
    slope_lookback: int = Field(default=5, ge=1, le=1000)
    breakout_length: int = Field(default=20, ge=2, le=2000)
    atr_length: int = Field(default=14, ge=2, le=1000)
    atr_reference_length: Literal[50] = 50
    atr_expansion_threshold: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    atr_stop_multiplier: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    reward_risk: float = Field(default=2.0, gt=0, allow_inf_nan=False)


class TrendVolatilityBreakoutV1Strategy(BaseStrategy[Parameters]):
    name = "trend_volatility_breakout_v1"
    version = "1.0.1"
    description = "EMA trend and slope + prior channel breakout + ATR expansion; single 1h"
    status = "research"
    created_at = "2026-10-04T00:00:00+00:00"
    lab_timeframes = ("1h",)
    lab_modes = ("LONG_ONLY", "SHORT_ONLY", "LONG_SHORT")
    lab_risk_parameters = {
        "atr_length": "atr_period",
        "atr_stop_multiplier": "atr_multiplier",
        "reward_risk": "risk_reward",
    }
    parameter_model = Parameters

    @classmethod
    def required_warmup(cls, parameters, timeframe):
        if timeframe != "1h":
            raise ValueError("trend_volatility_breakout_v1 requires timeframe 1h")
        p = Parameters.model_validate(parameters)
        # Five EMA lengths suppress seed influence; context signals cannot enter
        # a study position. Slope availability remains part of readiness below.
        return max(
            p.trend_length * 5,
            p.breakout_length + 1,
            p.atr_length + p.atr_reference_length + 1,
        )

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        self.required_warmup(self.parameters.model_dump(), self.config.market.timeframe)
        if not isinstance(candles.index, pd.DatetimeIndex):
            raise ValueError("Candles require a UTC DatetimeIndex")
        if not candles.index.is_monotonic_increasing or candles.index.has_duplicates:
            raise ValueError("Candles must be sorted without duplicate timestamps")
        if str(candles.index.tz) != "UTC" or (candles.index != candles.index.floor("h")).any():
            raise ValueError("Candles must be aligned 1h UTC")
        if candles.empty:
            return self._features(candles)
        segments = (candles.index.to_series().diff() != pd.Timedelta(hours=1)).cumsum()
        return pd.concat([self._features(part) for _, part in candles.groupby(segments)])

    def _features(self, candles):
        p = self.parameters
        f = candles.copy()
        f["trend_ema"] = ema(candles.close, p.trend_length)
        f["trend_slope"] = f.trend_ema - f.trend_ema.shift(p.slope_lookback)
        f["breakout_high"] = candles.high.shift(1).rolling(p.breakout_length).max()
        f["breakout_low"] = candles.low.shift(1).rolling(p.breakout_length).min()
        f["atr"] = atr(candles, p.atr_length)
        # Prior 50 complete ATR observations, excluding the signal bar.
        f["atr_reference"] = f.atr.shift(1).rolling(p.atr_reference_length).mean()
        f["atr_expansion"] = f.atr / f.atr_reference.where(f.atr_reference > 0)
        f["available_at"] = f.index + pd.Timedelta(hours=1)
        f["ready"] = f[
            ["trend_ema", "trend_slope", "breakout_high", "breakout_low", "atr_expansion"]
        ].notna().all(axis=1) & (f.atr > 0)
        f["ready"] &= pd.Series(range(1, len(f) + 1), index=f.index) >= self.required_warmup(
            p.model_dump(), "1h"
        )
        return f

    def generate_long_entries(self, f):
        return (
            (
                f.ready
                & (f.close > f.trend_ema)
                & (f.trend_slope > 0)
                & (f.close > f.breakout_high)
                & (f.atr_expansion >= self.parameters.atr_expansion_threshold)
            )
            .fillna(False)
            .tolist()
        )

    def generate_short_entries(self, f):
        return (
            (
                f.ready
                & (f.close < f.trend_ema)
                & (f.trend_slope < 0)
                & (f.close < f.breakout_low)
                & (f.atr_expansion >= self.parameters.atr_expansion_threshold)
            )
            .fillna(False)
            .tolist()
        )

    def generate_long_exits(self, features):
        return [False] * len(features)

    def generate_short_exits(self, features):
        return [False] * len(features)
