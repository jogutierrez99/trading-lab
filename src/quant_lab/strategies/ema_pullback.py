"""EMA_PULLBACK_001: previous-bar touch, then a close-time recovery."""

from typing import Literal

import pandas as pd

from quant_lab.config import StrictModel
from quant_lab.features import ema, rsi
from quant_lab.strategies._long_only import LongOnlyStrategy


class Parameters(StrictModel):
    pullback_period: Literal[20, 30, 50] = 20


class EmaPullbackStrategy(LongOnlyStrategy):
    name = "ema_pullback"
    parameter_model = Parameters

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        result = candles.copy()
        result["ema50"] = ema(candles.close, 50)
        result["ema200"] = ema(candles.close, 200)
        result["pullback_ema"] = ema(candles.close, self.parameters.pullback_period)
        result["previous_touch"] = candles.low.shift(1) <= result.pullback_ema.shift(1)
        result["rsi"] = rsi(candles.close, 14)
        return result

    def generate_long_entries(self, f) -> list[bool]:
        return (
            f.previous_touch
            & (f.close > f.pullback_ema)
            & (f.rsi > 50)
            & (f.ema50 > f.ema200)
            & (f.close > f.ema200)
        ).tolist()

    def generate_long_exits(self, f) -> list[bool]:
        return (f.close < f.ema50).tolist()
