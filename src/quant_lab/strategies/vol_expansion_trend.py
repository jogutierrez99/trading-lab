"""VOL_EXPANSION_TREND_001: trend breakout with concurrent ATR expansion."""

from typing import Literal

import pandas as pd

from quant_lab.config import StrictModel
from quant_lab.features import atr, ema
from quant_lab.strategies._long_only import LongOnlyStrategy


class Parameters(StrictModel):
    percentile_pct: Literal[50, 60, 70] = 50


class VolExpansionTrendStrategy(LongOnlyStrategy):
    name = "vol_expansion_trend"
    parameter_model = Parameters

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        if self.config.market.timeframe != "1h":
            raise ValueError("Vol expansion trend v1 requires 1h data")
        f = candles.copy()
        f["ema50"] = ema(f.close, 50)
        f["ema200"] = ema(f.close, 200)
        f["roc7"] = f.close / f.close.shift(168) - 1
        f["atr"] = atr(f, 14)
        f["atr_ratio"] = f.atr / f.close
        f["ratio_sma24"] = f.atr_ratio.rolling(24).mean()
        f["threshold"] = (
            f.atr_ratio.shift(1).rolling(720).quantile(self.parameters.percentile_pct / 100)
        )
        f["prior_high"] = f.high.shift(1).rolling(24).max()
        return f

    def generate_long_entries(self, f) -> list[bool]:
        return (
            (f.ema50 > f.ema200)
            & (f.roc7 > 0)
            & (f.atr_ratio > f.ratio_sma24)
            & (f.atr_ratio > f.threshold)
            & (f.close > f.prior_high)
        ).tolist()

    def generate_long_exits(self, f) -> list[bool]:
        return ((f.close < f.ema50) | ((f.roc7 < 0) & (f.atr_ratio < f.ratio_sma24))).tolist()
