"""Directional RSI strength; not overbought/oversold contrarian logic."""

from pydantic import Field, model_validator

from quant_lab.config import StrictModel
from quant_lab.literature_features import LiteratureStrategy, trend_features


class Parameters(StrictModel):
    ema_period: int = Field(default=200, ge=2, le=1000)
    adx_period: int = Field(default=14, ge=2, le=1000)
    adx_threshold: float = Field(default=25.0, gt=0, le=100, allow_inf_nan=False)
    rsi_period: int = Field(default=14, ge=2, le=1000)
    long_threshold: float = Field(default=55.0, gt=50, lt=100, allow_inf_nan=False)
    short_threshold: float = Field(default=45.0, gt=0, lt=50, allow_inf_nan=False)
    atr_period: int = Field(default=14, ge=2, le=1000)
    stop_atr_multiplier: float = Field(default=2.0, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def symmetric(self):
        if abs(self.long_threshold + self.short_threshold - 100) > 1e-12:
            raise ValueError("RSI zones must be symmetric")
        return self


class RsiMomentumRegimeV1Strategy(LiteratureStrategy):
    name = "rsi_momentum_regime_v1"
    description = "EMA200 + ADX25 + RSI55/45 strength; RSI50 exit, initial 2ATR stop"
    lab_timeframes = ("4h",)
    parameter_model = Parameters
    lab_risk_parameters = {"atr_period": "atr_period", "stop_atr_multiplier": "atr_multiplier"}

    @classmethod
    def required_warmup(cls, parameters, timeframe):
        cls.check_timeframe(timeframe)
        p = Parameters.model_validate(parameters)
        return max(5 * p.ema_period, 5 * p.adx_period, 5 * p.rsi_period, p.atr_period + 1)

    def _features(self, candles):
        return trend_features(candles, self.parameters, True)

    def _entries(self, f, side):
        threshold = self.parameters.long_threshold if side == 1 else self.parameters.short_threshold
        return (
            f.ready
            & ((f.close - f.ema) * side > 0)
            & (f.adx > self.parameters.adx_threshold)
            & ((f.rsi - threshold) * side > 0)
        )

    def _exits(self, f, side):
        return f.ready & ((f.rsi - 50) * side <= 0)
