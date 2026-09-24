"""DONCHIAN_ADX_001: prior Donchian breakout plus EMA and Wilder ADX."""

import pandas as pd
from pydantic import Field

from quant_lab.config import StrictModel
from quant_lab.features import ema
from quant_lab.indicators import adx
from quant_lab.strategies._long_only import LongOnlyStrategy


class Parameters(StrictModel):
    donchian_period: int = Field(default=20, ge=2)
    adx_threshold: float = Field(default=20.0, ge=0, le=100, allow_inf_nan=False)


class DonchianAdxStrategy(LongOnlyStrategy):
    name = "donchian_adx"
    parameter_model = Parameters

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        result = candles.copy()
        result["upper"] = candles.high.shift(1).rolling(self.parameters.donchian_period).max()
        result["ema"] = ema(candles.close, 200)
        result["adx"] = adx(candles, 14)
        return result

    def generate_long_entries(self, features) -> list[bool]:
        return (
            (features.close > features.upper)
            & (features.close > features.ema)
            & (features.adx > self.parameters.adx_threshold)
        ).tolist()

    def generate_long_exits(self, features) -> list[bool]:
        return (features.close < features.ema).tolist()
