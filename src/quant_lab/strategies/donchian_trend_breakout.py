"""Prior Donchian breakout with a configurable causal trend filter."""

from pydantic import Field

from quant_lab.trend_expansion_features import EntryParameters, ExpansionStrategy


class Parameters(EntryParameters):
    breakout_length: int = Field(default=40, ge=2, le=2000)


class DonchianTrendBreakoutStrategy(ExpansionStrategy):
    name = "donchian_trend_breakout"
    description = "Previous-channel close breakout; symmetric long/short, ATR risk"
    parameter_model = Parameters

    def _features(self, candles):
        f = super()._features(candles)
        f["breakout_high"] = f.high.shift(1).rolling(self.parameters.breakout_length).max()
        f["breakout_low"] = f.low.shift(1).rolling(self.parameters.breakout_length).min()
        return f

    def _entries(self, f, side):
        crossed = f.close > f.breakout_high if side == 1 else f.close < f.breakout_low
        return f.ready & self.regime(f, side) & crossed
