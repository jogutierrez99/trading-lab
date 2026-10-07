"""Reuse frozen Trend Volatility Breakout entries; opt-in Donchian signal exits."""

from typing import Literal

from pydantic import Field

from quant_lab.strategies.trend_volatility_breakout_v1 import Parameters as FrozenParameters
from quant_lab.strategies.trend_volatility_breakout_v1 import TrendVolatilityBreakoutV1Strategy
from quant_lab.trend_expansion_features import channel_exit, exit_features


class Parameters(FrozenParameters):
    exit_method: Literal["risk", "donchian"] = "risk"
    exit_length: int = Field(default=10, ge=2, le=2000)


class DonchianAtrBreakoutStrategy(TrendVolatilityBreakoutV1Strategy):
    name = "donchian_atr_breakout"
    version = "1.0.0"
    created_at = "2026-10-06T00:00:00+00:00"
    description = "Frozen EMA/slope/Donchian/ATR entry reuse with optional Donchian exits"
    parameter_model = Parameters

    @classmethod
    def required_warmup(cls, parameters, timeframe):
        p = Parameters.model_validate(parameters)
        original = {k: v for k, v in p.model_dump().items() if k in FrozenParameters.model_fields}
        return max(
            super().required_warmup(original, timeframe),
            p.trend_length + p.slope_lookback,
            p.exit_length + 1,
        )

    def _features(self, candles):
        return exit_features(super()._features(candles), self.parameters.exit_length)

    def generate_long_exits(self, f):
        return channel_exit(f, self.parameters.exit_method, 1)

    def generate_short_exits(self, f):
        return channel_exit(f, self.parameters.exit_method, -1)
