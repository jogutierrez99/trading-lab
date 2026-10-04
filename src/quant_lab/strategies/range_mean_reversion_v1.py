"""Sideways regime -> failed excursion -> frozen range midpoint; RESEARCH ONLY."""

import pandas as pd
from pydantic import Field, model_validator

from quant_lab.config import StrictModel
from quant_lab.features import atr
from quant_lab.intraday_features import context, context_warmup, ready, segmented
from quant_lab.strategies.base import BaseStrategy


class Parameters(StrictModel):
    adx_period: int = Field(default=14, ge=2, le=1000)
    adx_threshold: float = Field(default=20.0, gt=0, le=100, allow_inf_nan=False)
    ema_period: int = Field(default=100, ge=2, le=500)
    ema_slope_lookback: int = Field(default=3, ge=1, le=100)
    max_ema_slope_pct: float = Field(default=0.10, gt=0, allow_inf_nan=False)
    range_lookback: int = Field(default=32, ge=2, le=2000)
    lower_zone: float = Field(default=0.20, gt=0, lt=0.5, allow_inf_nan=False)
    upper_zone: float = Field(default=0.80, gt=0.5, lt=1, allow_inf_nan=False)
    atr_period: int = Field(default=14, ge=2, le=1000)
    minimum_range_atr: float = Field(default=3.0, gt=0, allow_inf_nan=False)
    stop_atr_buffer: float = Field(default=0.50, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def symmetric(self):
        if abs(self.lower_zone + self.upper_zone - 1) > 1e-12:
            raise ValueError("Range zones must be symmetric around midpoint")
        return self


class RangeMeanReversionV1Strategy(BaseStrategy[Parameters]):
    name = "range_mean_reversion_v1"
    version = "1.0.0"
    description = "15m failed range excursions; closed 1h low ADX/flat EMA; midpoint target"
    status = "research"
    created_at = "2026-10-04T00:00:00+00:00"
    lab_timeframes = ("15m",)
    lab_price_levels = True
    lab_extended_metrics = True
    lab_risk_parameters = {"atr_period": "atr_period"}
    parameter_model = Parameters

    @classmethod
    def required_warmup(cls, parameters, timeframe):
        if timeframe != "15m":
            raise ValueError("Range mean reversion requires 15m execution")
        p = Parameters.model_validate(parameters)
        return max(
            context_warmup(p.ema_period, p.ema_slope_lookback, p.adx_period),
            p.range_lookback + 1,
            p.atr_period + 1,
        )

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        self.required_warmup(self.parameters.model_dump(), self.config.market.timeframe)
        return segmented(candles, self._features)

    def _features(self, candles):
        p = self.parameters
        f = candles.copy().join(context(candles, p.ema_period, p.ema_slope_lookback, p.adx_period))
        f["atr"] = atr(candles, p.atr_period)
        f["range_high"] = candles.high.shift(1).rolling(p.range_lookback).max()
        f["range_low"] = candles.low.shift(1).rolling(p.range_lookback).min()
        width = f.range_high - f.range_low
        f["range_mid"] = (f.range_high + f.range_low) / 2
        f["range_position"] = (f.close - f.range_low) / width.where(width > 0)
        f["range_width_atr"] = width / f.atr.where(f.atr > 0)
        f["ready"] = ready(
            f,
            p.ema_period,
            [
                "hour_adx",
                "hour_ema",
                "hour_slope_pct",
                "range_high",
                "range_low",
                "range_position",
                "range_width_atr",
            ],
        )
        f["range_regime"] = (
            f.ready
            & (f.hour_adx < p.adx_threshold)
            & (f.hour_slope_pct.abs() < p.max_ema_slope_pct)
        )
        f["long_stop"] = f.range_low - p.stop_atr_buffer * f.atr
        f["short_stop"] = f.range_high + p.stop_atr_buffer * f.atr
        f["long_target"] = f["short_target"] = f.range_mid
        return f

    def generate_long_entries(self, f):
        return (
            (
                f.range_regime
                & (f.range_width_atr >= self.parameters.minimum_range_atr)
                & (f.low < f.range_low)
                & (f.close > f.range_low)
                & (f.range_position < self.parameters.lower_zone)
            )
            .fillna(False)
            .tolist()
        )

    def generate_short_entries(self, f):
        return (
            (
                f.range_regime
                & (f.range_width_atr >= self.parameters.minimum_range_atr)
                & (f.high > f.range_high)
                & (f.close < f.range_high)
                & (f.range_position > self.parameters.upper_zone)
            )
            .fillna(False)
            .tolist()
        )

    def generate_long_exits(self, f):
        return (f.ready & ~f.range_regime).fillna(False).tolist()

    def generate_short_exits(self, f):
        return self.generate_long_exits(f)

    def entry_levels(self, candles):
        return self.prepare_features(candles)[
            ["long_stop", "long_target", "short_stop", "short_target"]
        ]
