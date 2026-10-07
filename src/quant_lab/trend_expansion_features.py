"""Causal hourly components; execution stays in StudyBackend."""

from abc import abstractmethod
from typing import Literal

import pandas as pd
from pydantic import Field, model_validator

from quant_lab.config import StrictModel
from quant_lab.features import atr, ema
from quant_lab.literature_features import segmented
from quant_lab.strategies.base import BaseStrategy


class EntryParameters(StrictModel):
    trend_filter: Literal["ema_slope", "price_ema", "dual_ema", "off"] = "ema_slope"
    trend_length: int = Field(default=200, ge=2, le=2000)
    fast_length: int = Field(default=50, ge=2, le=2000)
    slope_lookback: int = Field(default=5, ge=1, le=1000)
    atr_length: int = Field(default=14, ge=2, le=1000)
    atr_stop_multiplier: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    reward_risk: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    exit_method: Literal["risk", "donchian"] = "risk"
    exit_length: int = Field(default=10, ge=2, le=2000)

    @model_validator(mode="after")
    def ema_order(self):
        if self.fast_length >= self.trend_length:
            raise ValueError("fast_length must precede trend_length")
        return self


def exit_features(f, length):
    f["exit_low"] = f.low.shift(1).rolling(length).min()
    f["exit_high"] = f.high.shift(1).rolling(length).max()
    return f


def channel_exit(f, method, side):
    if method == "risk":
        return [False] * len(f)
    crossed = f.close < f.exit_low if side == 1 else f.close > f.exit_high
    return crossed.fillna(False).tolist()


class ExpansionStrategy(BaseStrategy):
    created_at = "2026-10-06T00:00:00+00:00"
    lab_risk_parameters = {
        "atr_length": "atr_period",
        "atr_stop_multiplier": "atr_multiplier",
        "reward_risk": "risk_reward",
    }

    @classmethod
    def required_warmup(cls, parameters, timeframe):
        if timeframe != "1h":
            raise ValueError("Trend Expansion requires 1h")
        p = cls.parameter_model.model_validate(parameters)
        return max(
            5 * p.trend_length,
            p.trend_length + p.slope_lookback,
            p.atr_length + getattr(p, "atr_reference_length", 0) + 1,
            getattr(p, "breakout_length", 1) + 1,
            p.exit_length + 1,
        )

    def prepare_features(self, candles):
        self.required_warmup(self.parameters.model_dump(), self.config.market.timeframe)
        return segmented(candles, "1h", self._features)

    def _features(self, candles):
        p = self.parameters
        f = candles.copy()
        f["trend_ema"] = ema(f.close, p.trend_length)
        f["fast_ema"] = ema(f.close, p.fast_length)
        f["trend_slope"] = f.trend_ema - f.trend_ema.shift(p.slope_lookback)
        f["atr"] = atr(f, p.atr_length)
        f["available_at"] = f.index + pd.Timedelta(hours=1)
        f["ready"] = (
            pd.Series(range(1, len(f) + 1), index=f.index)
            >= self.required_warmup(p.model_dump(), "1h")
        ) & (f.atr > 0)
        return exit_features(f, p.exit_length)

    def regime(self, f, side):
        method = self.parameters.trend_filter
        if method == "off":
            return pd.Series(True, index=f.index)
        if method == "dual_ema":
            return (f.fast_ema - f.trend_ema) * side > 0
        allowed = (f.close - f.trend_ema) * side > 0
        return allowed & (f.trend_slope * side > 0) if method == "ema_slope" else allowed

    @abstractmethod
    def _entries(self, features, side): ...

    def generate_long_entries(self, f):
        return self._entries(f, 1).fillna(False).tolist()

    def generate_short_entries(self, f):
        return self._entries(f, -1).fillna(False).tolist()

    def generate_long_exits(self, f):
        return channel_exit(f, self.parameters.exit_method, 1)

    def generate_short_exits(self, f):
        return channel_exit(f, self.parameters.exit_method, -1)
