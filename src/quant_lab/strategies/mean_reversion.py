"""MEANREV_001: Bollinger deviations and Wilder RSI, with mean/RSI exits."""

import pandas as pd
from pydantic import Field

from quant_lab.config import StrictModel
from quant_lab.features import rsi, sma
from quant_lab.strategies.base import BaseStrategy


class Parameters(StrictModel):
    bollinger_period: int = Field(default=20, ge=2)
    bollinger_std: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    rsi_period: int = Field(default=14, ge=2)
    rsi_long: float = Field(default=30.0, gt=0, lt=50, allow_inf_nan=False)
    rsi_short: float = Field(default=70.0, gt=50, lt=100, allow_inf_nan=False)


class MeanReversion(BaseStrategy[Parameters]):
    lab_timeframes = ("1h", "4h", "1d")  # Periods are bars, not elapsed hours.
    name = "mean_reversion"
    parameter_model = Parameters

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        result = candles.copy()
        p = self.parameters
        result["middle"] = sma(candles.close, p.bollinger_period)
        width = candles.close.rolling(p.bollinger_period).std(ddof=0) * p.bollinger_std
        result["lower"] = result.middle - width
        result["upper"] = result.middle + width
        result["rsi"] = rsi(candles.close, p.rsi_period)
        return result

    def generate_long_entries(self, features):
        return (
            (features.close < features.lower) & (features.rsi < self.parameters.rsi_long)
        ).tolist()

    def generate_short_entries(self, features):
        return (
            (features.close > features.upper) & (features.rsi > self.parameters.rsi_short)
        ).tolist()

    def generate_long_exits(self, features):
        return ((features.close >= features.middle) | (features.rsi >= 50)).tolist()

    def generate_short_exits(self, features):
        return ((features.close <= features.middle) | (features.rsi <= 50)).tolist()
