"""Directional ATR impulse and volatility expansion, without a Donchian entry."""

from typing import Literal

from pydantic import Field

from quant_lab.trend_expansion_features import EntryParameters, ExpansionStrategy


class Parameters(EntryParameters):
    atr_reference_length: int = Field(default=50, ge=2, le=2000)
    atr_reference_method: Literal["mean", "median"] = "mean"
    atr_expansion_threshold: float = Field(default=1.1, gt=0, allow_inf_nan=False)
    impulse_atr_multiplier: float = Field(default=1.0, gt=0, allow_inf_nan=False)


class AtrVolatilityBreakoutStrategy(ExpansionStrategy):
    name = "atr_volatility_breakout"
    description = "Close displacement beyond prior ATR plus causal ATR expansion"
    parameter_model = Parameters

    def _features(self, candles):
        f = super()._features(candles)
        p = self.parameters
        history = f.atr.shift(1).rolling(p.atr_reference_length)
        f["atr_reference"] = (
            history.mean() if p.atr_reference_method == "mean" else history.median()
        )
        f["atr_expansion"] = f.atr / f.atr_reference.where(f.atr_reference > 0)
        f["impulse"] = (f.close - f.close.shift(1)) / f.atr.shift(1).where(f.atr.shift(1) > 0)
        return f

    def _entries(self, f, side):
        p = self.parameters
        return (
            f.ready
            & self.regime(f, side)
            & (f.impulse * side > p.impulse_atr_multiplier)
            & (f.atr_expansion >= p.atr_expansion_threshold)
        )
