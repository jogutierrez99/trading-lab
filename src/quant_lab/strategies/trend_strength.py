"""TREND_STRENGTH_001: structural EMA trend, slope and two causal ROC horizons."""

from typing import Literal

import pandas as pd
from pydantic import model_validator

from quant_lab.config import StrictModel
from quant_lab.features import ema
from quant_lab.strategies._long_only import LongOnlyStrategy


class Parameters(StrictModel):
    short_days: Literal[7, 14] = 7
    long_days: Literal[30, 60] = 30

    @model_validator(mode="after")
    def allowed_pair(self):
        if (self.short_days, self.long_days) not in {(7, 30), (14, 30), (7, 60)}:
            raise ValueError("Only the three predefined ROC pairs are permitted")
        return self


class TrendStrengthStrategy(LongOnlyStrategy):
    name = "trend_strength"
    parameter_model = Parameters

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        if self.config.market.timeframe != "1h":
            raise ValueError("Trend strength v1 requires 1h data")
        result = candles.copy()
        result["ema50"] = ema(candles.close, 50)
        result["ema200"] = ema(candles.close, 200)
        result["ema50_prior"] = result.ema50.shift(24)
        result["roc_short"] = (
            candles.close / candles.close.shift(self.parameters.short_days * 24) - 1
        )
        result["roc_long"] = candles.close / candles.close.shift(self.parameters.long_days * 24) - 1
        result["prior_high"] = candles.high.shift(1).rolling(48).max()
        return result

    def generate_long_entries(self, f) -> list[bool]:
        return (
            (f.ema50 > f.ema200)
            & (f.ema50 > f.ema50_prior)
            & (f.roc_short > 0)
            & (f.roc_long > 0)
            & (f.close > f.prior_high)
        ).tolist()

    def generate_long_exits(self, f) -> list[bool]:
        return ((f.roc_short < 0) | (f.close < f.ema50)).tolist()
