"""ATR_BREAKOUT_001: expansion beyond previous ATR with a prior quantile gate."""

from typing import Literal

import pandas as pd

from quant_lab.config import StrictModel
from quant_lab.features import atr, ema
from quant_lab.strategies._long_only import LongOnlyStrategy


class Parameters(StrictModel):
    expansion_k: Literal[1.0, 1.5, 2.0] = 1.0


class AtrBreakoutStrategy(LongOnlyStrategy):
    name = "atr_breakout"
    parameter_model = Parameters

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        result = candles.copy()
        result["ema50"] = ema(candles.close, 50)
        result["ema200"] = ema(candles.close, 200)
        result["atr"] = atr(candles, 14)
        result["atr_ratio"] = result.atr / candles.close
        result["threshold"] = result.atr_ratio.shift(1).rolling(720).quantile(0.6)
        result["breakout_level"] = candles.close.shift(
            1
        ) + self.parameters.expansion_k * result.atr.shift(1)
        return result

    def generate_long_entries(self, f) -> list[bool]:
        return (
            (f.close > f.ema200) & (f.close > f.breakout_level) & (f.atr_ratio > f.threshold)
        ).tolist()

    def generate_long_exits(self, f) -> list[bool]:
        return (f.close < f.ema50).tolist()
