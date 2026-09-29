"""SMA trend / RSI pullback; causal single-timeframe and completed-hour variants."""

from typing import Literal

import pandas as pd
from pydantic import Field, model_validator

from quant_lab.config import StrictModel
from quant_lab.features import atr, rsi, sma
from quant_lab.mtf_features import closed_features
from quant_lab.strategies.base import BaseStrategy


class Parameters(StrictModel):
    variant: Literal["V1", "V2", "V3"] = "V1"
    sma_length: int = Field(default=185, ge=2, le=2000)
    rsi_length: int = Field(default=25, ge=2, le=1000)
    rsi_oversold: int = Field(default=30, gt=0, lt=50)
    rsi_overbought: int | None = Field(default=None, gt=50, lt=100)
    atr_length: int = Field(default=14, ge=2, le=1000)
    atr_multiplier: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    reward_risk: float = Field(default=1.5, gt=0, allow_inf_nan=False)
    sma_slope_lookback: Literal[5] = 5

    @model_validator(mode="after")
    def mirror(self):
        expected = 100 - self.rsi_oversold
        if self.rsi_overbought is not None and self.rsi_overbought != expected:
            raise ValueError("rsi_overbought must equal 100 - rsi_oversold")
        object.__setattr__(self, "rsi_overbought", expected)
        return self


class TrendRsiPullbackV1Strategy(BaseStrategy[Parameters]):
    name = "trend_rsi_pullback_v1"
    version = "1.0.0"
    description = "RSI pullback against SMA trend; V1 15m, V2 closed 1h, V3 closed 1h slope"
    status = "research"
    created_at = "2026-09-29T00:00:00+00:00"
    lab_timeframes = ("15m",)
    lab_modes = ("LONG_ONLY", "SHORT_ONLY", "LONG_SHORT")
    lab_risk_parameters = {
        "atr_length": "atr_period",
        "atr_multiplier": "atr_multiplier",
        "reward_risk": "risk_reward",
    }
    parameter_model = Parameters

    @classmethod
    def required_warmup(cls, parameters, timeframe):
        p = Parameters.model_validate(parameters)
        trend = p.sma_length + (p.sma_slope_lookback if p.variant == "V3" else 0)
        trend = 4 * max(250, trend) + 4 if p.variant != "V1" else trend
        return max(1004, trend, p.rsi_length + 1, p.atr_length + 1)

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        if self.config.market.timeframe != "15m":
            raise ValueError("trend_rsi_pullback_v1 requires entry timeframe 15m")
        if not candles.index.is_monotonic_increasing or candles.index.has_duplicates:
            raise ValueError("Candles must be sorted without duplicate timestamps")
        if str(candles.index.tz) != "UTC" or (candles.index != candles.index.floor("15min")).any():
            raise ValueError("Candles must be aligned 15m UTC")
        if candles.empty:
            return self._features(candles)
        # A source gap starts fresh indicator/warmup history; no rolling across gaps.
        segments = (candles.index.to_series().diff() != pd.Timedelta(minutes=15)).cumsum()
        return pd.concat([self._features(part) for _, part in candles.groupby(segments)])

    def _features(self, candles):
        p = self.parameters
        result = candles.copy()
        result["rsi"] = rsi(candles.close, p.rsi_length)
        result["atr"] = atr(candles, p.atr_length)

        def trend(frame):
            f = pd.DataFrame(index=frame.index)
            f["trend_close"] = frame.close
            f["trend_sma"] = sma(frame.close, p.sma_length)
            f["trend_slope"] = f.trend_sma - f.trend_sma.shift(p.sma_slope_lookback)
            f["trend_count"] = pd.Series(range(1, len(frame) + 1), index=frame.index, dtype=float)
            return f

        if p.variant == "V1":
            result = result.join(trend(candles))
            result["available_at"] = result.index + pd.Timedelta(minutes=15)
        else:
            result = result.join(closed_features(candles, "15m", "1h", calculator=trend))
        valid = result[["rsi", "atr", "trend_close", "trend_sma"]].notna().all(axis=1)
        valid &= result.atr > 0
        if p.variant == "V3":
            valid &= result.trend_slope.notna()
        if p.variant != "V1":
            valid &= result.trend_count >= 250
        result["ready"] = valid & (pd.Series(range(1, len(result) + 1), index=result.index) >= 1000)
        return result

    def generate_long_entries(self, f):
        direction = f.trend_close > f.trend_sma
        if self.parameters.variant == "V3":
            direction &= f.trend_slope > 0
        return (f.ready & direction & (f.rsi < self.parameters.rsi_oversold)).fillna(False).tolist()

    def generate_short_entries(self, f):
        direction = f.trend_close < f.trend_sma
        if self.parameters.variant == "V3":
            direction &= f.trend_slope < 0
        return (
            (f.ready & direction & (f.rsi > self.parameters.rsi_overbought)).fillna(False).tolist()
        )

    def generate_long_exits(self, features):
        return [False] * len(features)

    def generate_short_exits(self, features):
        return [False] * len(features)
