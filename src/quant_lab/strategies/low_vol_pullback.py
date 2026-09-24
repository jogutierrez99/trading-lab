"""LOW_VOL_PULLBACK_001: previous EMA20 touch gated by low current volatility."""

from typing import Literal

import pandas as pd

from quant_lab.config import StrictModel
from quant_lab.features import atr, ema, rsi
from quant_lab.strategies._long_only import LongOnlyStrategy


class Parameters(StrictModel):
    percentile_pct: Literal[30, 40, 50] = 30


class LowVolPullbackStrategy(LongOnlyStrategy):
    name = "low_vol_pullback"
    parameter_model = Parameters

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        if self.config.market.timeframe != "1h":
            raise ValueError("Low vol pullback v1 requires 1h data")
        f = candles.copy()
        f["ema20"] = ema(f.close, 20)
        f["ema50"] = ema(f.close, 50)
        f["ema200"] = ema(f.close, 200)
        f["rsi"] = rsi(f.close, 14)
        f["atr"] = atr(f, 14)
        f["atr_ratio"] = f.atr / f.close
        previous = f.atr_ratio.shift(1).rolling(720)
        f["threshold"] = previous.quantile(self.parameters.percentile_pct / 100)
        f["exit_threshold"] = previous.quantile(0.7)
        f["previous_touch"] = f.low.shift(1) <= f.ema20.shift(1)
        return f

    def generate_long_entries(self, f) -> list[bool]:
        return (
            (f.ema50 > f.ema200)
            & (f.close > f.ema200)
            & f.previous_touch
            & (f.close > f.ema20)
            & (f.rsi > 50)
            & (f.atr_ratio < f.threshold)
        ).tolist()

    def generate_long_exits(self, f) -> list[bool]:
        return ((f.close < f.ema50) | (f.atr_ratio > f.exit_threshold)).tolist()
