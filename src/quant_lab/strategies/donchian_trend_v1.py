"""Prior channel breakout, structural direction and trend strength; RESEARCH ONLY."""

from pydantic import Field

from quant_lab.config import StrictModel
from quant_lab.literature_features import LiteratureStrategy, trend_features


class Parameters(StrictModel):
    ema_period: int = Field(default=200, ge=2, le=1000)
    adx_period: int = Field(default=14, ge=2, le=1000)
    adx_threshold: float = Field(default=25.0, gt=0, le=100, allow_inf_nan=False)
    donchian_lookback: int = Field(default=20, ge=2, le=2000)
    atr_period: int = Field(default=14, ge=2, le=1000)
    breakout_strength_min: float = Field(default=0.10, gt=0, allow_inf_nan=False)
    stop_atr_multiplier: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    trailing_atr_multiplier: float = Field(default=2.0, gt=0, allow_inf_nan=False)


class DonchianTrendV1Strategy(LiteratureStrategy):
    name = "donchian_trend_v1"
    description = "Prior Donchian20, EMA200/slope and ADX25; close-based 2ATR trailing"
    lab_timeframes = ("4h",)
    parameter_model = Parameters
    lab_risk_parameters = {
        "atr_period": "atr_period",
        "stop_atr_multiplier": "atr_multiplier",
        "trailing_atr_multiplier": "trailing_atr_multiplier",
    }

    @classmethod
    def required_warmup(cls, parameters, timeframe):
        cls.check_timeframe(timeframe)
        p = Parameters.model_validate(parameters)
        return max(5 * p.ema_period, 5 * p.adx_period, p.donchian_lookback + 1, p.atr_period + 1)

    def _features(self, candles):
        f = trend_features(candles, self.parameters)
        f["donchian_high"] = f.high.shift(1).rolling(self.parameters.donchian_lookback).max()
        f["donchian_low"] = f.low.shift(1).rolling(self.parameters.donchian_lookback).min()
        f["long_strength"] = (f.close - f.donchian_high) / f.atr.where(f.atr > 0)
        f["short_strength"] = (f.donchian_low - f.close) / f.atr.where(f.atr > 0)
        return f

    def _entries(self, f, side):
        strength = f.long_strength if side == 1 else f.short_strength
        return (
            f.ready
            & ((f.close - f.ema) * side > 0)
            & (f.ema_slope * side >= 0)
            & (f.adx > self.parameters.adx_threshold)
            & (strength > self.parameters.breakout_strength_min)
        )

    def _exits(self, f, side):
        return f.ready & False
