"""TREND_001: prior-candle Donchian breakout with a causal EMA filter."""

import pandas as pd
from pydantic import Field

from quant_lab.config import StrictModel
from quant_lab.features import ema
from quant_lab.strategies.base import BaseStrategy


class Parameters(StrictModel):
    donchian_period: int = Field(default=20, ge=2)
    ema_period: int = Field(default=200, ge=2)


class TrendFollowing(BaseStrategy[Parameters]):
    lab_timeframes = ("1h", "4h", "1d")  # Periods are bars, not elapsed hours.
    name = "trend_following"
    parameter_model = Parameters

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        result = candles.copy()
        p = self.parameters
        result["upper"] = candles.high.shift(1).rolling(p.donchian_period).max()
        result["lower"] = candles.low.shift(1).rolling(p.donchian_period).min()
        result["ema"] = ema(candles.close, p.ema_period)
        return result

    def generate_long_entries(self, features):
        return ((features.close > features.upper) & (features.close > features.ema)).tolist()

    def generate_short_entries(self, features):
        return ((features.close < features.lower) & (features.close < features.ema)).tolist()

    def generate_long_exits(self, features):
        # Position-dependent trailing belongs to execution, not this signal module.
        return [False] * len(features)

    def generate_short_exits(self, features):
        return [False] * len(features)
