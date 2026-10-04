"""Compression -> directional breakout -> ATR expansion; RESEARCH ONLY."""

import pandas as pd
from pydantic import Field

from quant_lab.config import StrictModel
from quant_lab.features import atr
from quant_lab.indicators import bollinger
from quant_lab.intraday_features import context, context_warmup, ready, segmented
from quant_lab.strategies.base import BaseStrategy


class Parameters(StrictModel):
    ema_period: int = Field(default=100, ge=2, le=500)
    ema_slope_lookback: int = Field(default=3, ge=1, le=100)
    compression_window: int = Field(default=60, ge=2, le=2000)
    compression_ratio: float = Field(default=0.75, gt=0, le=1, allow_inf_nan=False)
    breakout_lookback: int = Field(default=20, ge=2, le=2000)
    atr_period: int = Field(default=14, ge=2, le=1000)
    atr_reference_window: int = Field(default=20, ge=2, le=1000)
    atr_expansion_factor: float = Field(default=1.10, ge=1, allow_inf_nan=False)
    momentum_threshold: float = Field(default=0.50, gt=0, allow_inf_nan=False)
    stop_atr_multiplier: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    reward_risk: float = Field(default=2.0, gt=0, allow_inf_nan=False)


class VolatilityBreakoutIntradayV1Strategy(BaseStrategy[Parameters]):
    name = "volatility_breakout_intraday_v1"
    version = "1.0.0"
    description = "15m compression breakout/ATR/body momentum with closed 1h EMA regime"
    status = "research"
    created_at = "2026-10-04T00:00:00+00:00"
    lab_timeframes = ("15m",)
    lab_extended_metrics = True
    lab_risk_parameters = {
        "atr_period": "atr_period",
        "stop_atr_multiplier": "atr_multiplier",
        "reward_risk": "risk_reward",
    }
    parameter_model = Parameters

    @classmethod
    def required_warmup(cls, parameters, timeframe):
        if timeframe != "15m":
            raise ValueError("Intraday breakout requires 15m execution")
        p = Parameters.model_validate(parameters)
        return max(
            context_warmup(p.ema_period, p.ema_slope_lookback),
            20 + p.compression_window + 1,
            p.breakout_lookback + 1,
            p.atr_period + p.atr_reference_window + 1,
        )

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        self.required_warmup(self.parameters.model_dump(), self.config.market.timeframe)
        return segmented(candles, self._features)

    def _features(self, candles):
        p = self.parameters
        f = candles.copy().join(context(candles, p.ema_period, p.ema_slope_lookback))
        f["atr"] = atr(candles, p.atr_period)
        f["atr_reference"] = f.atr.shift(1).rolling(p.atr_reference_window).mean()
        bandwidth = bollinger(candles.close, 20, 2.0).bandwidth
        f["prior_bandwidth"] = bandwidth.shift(1)
        f["compression_reference"] = bandwidth.shift(2).rolling(p.compression_window).median()
        f["compressed"] = f.prior_bandwidth <= p.compression_ratio * f.compression_reference
        f["breakout_high"] = candles.high.shift(1).rolling(p.breakout_lookback).max()
        f["breakout_low"] = candles.low.shift(1).rolling(p.breakout_lookback).min()
        f["atr_expansion"] = f.atr / f.atr_reference.where(f.atr_reference > 0)
        f["body_atr"] = (f.close - f.open) / f.atr.where(f.atr > 0)
        f["ready"] = ready(
            f,
            p.ema_period,
            [
                "hour_close",
                "hour_ema",
                "hour_slope",
                "compression_reference",
                "prior_bandwidth",
                "breakout_high",
                "breakout_low",
                "atr_expansion",
                "body_atr",
            ],
        )
        return f

    def _entries(self, f, side):
        level = f.breakout_high if side == 1 else f.breakout_low
        return (
            (
                f.ready
                & f.compressed
                & ((f.hour_close - f.hour_ema) * side > 0)
                & (f.hour_slope * side > 0)
                & ((f.close - level) * side > 0)
                & (f.atr_expansion >= self.parameters.atr_expansion_factor)
                & (f.body_atr * side >= self.parameters.momentum_threshold)
            )
            .fillna(False)
            .tolist()
        )

    def generate_long_entries(self, f):
        return self._entries(f, 1)

    def generate_short_entries(self, f):
        return self._entries(f, -1)

    def generate_long_exits(self, f):
        return [False] * len(f)

    def generate_short_exits(self, f):
        return [False] * len(f)
