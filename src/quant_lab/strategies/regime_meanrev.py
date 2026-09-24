"""REGIME_MEANREV_001: Bollinger/RSI entries only within a quiet EMA regime."""

import pandas as pd
from pydantic import Field

from quant_lab.config import StrictModel
from quant_lab.features import ema, rsi
from quant_lab.indicators import adx, bollinger
from quant_lab.strategies._long_only import LongOnlyStrategy


class Parameters(StrictModel):
    rsi_entry: float = Field(default=30.0, gt=0, lt=55, allow_inf_nan=False)


class RegimeMeanrevStrategy(LongOnlyStrategy):
    name = "regime_meanrev"
    parameter_model = Parameters

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        result = candles.copy().join(bollinger(candles.close))
        result["ema"] = ema(candles.close, 200)
        result["rsi"] = rsi(candles.close, 14)
        result["adx"] = adx(candles, 14)
        result["distance"] = (candles.close - result.ema).abs() / result.ema
        return result

    def generate_long_entries(self, features) -> list[bool]:
        return (
            (features.close < features.lower)
            & (features.rsi < self.parameters.rsi_entry)
            & (features.adx < 20)
            & (features.distance < 0.05)
        ).tolist()

    def generate_long_exits(self, features) -> list[bool]:
        return ((features.close >= features.middle) | (features.rsi > 55)).tolist()
