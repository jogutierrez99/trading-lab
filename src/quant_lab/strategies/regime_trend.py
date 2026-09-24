"""REGIME_TREND_001: structural trend, ADX strength and causal volatility gate."""

from typing import Literal

import pandas as pd

from quant_lab.config import StrictModel
from quant_lab.features import atr, ema
from quant_lab.indicators import adx
from quant_lab.strategies._long_only import LongOnlyStrategy


class Parameters(StrictModel):
    adx_threshold: Literal[18, 22, 25] = 18


class RegimeTrendStrategy(LongOnlyStrategy):
    name = "regime_trend"
    parameter_model = Parameters

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        if self.config.market.timeframe != "1h":
            raise ValueError("Regime trend v1 requires 1h data")
        f = candles.copy()
        f["ema50"] = ema(f.close, 50)
        f["ema200"] = ema(f.close, 200)
        f["adx"] = adx(f, 14)
        f["roc30"] = f.close / f.close.shift(720) - 1
        f["atr"] = atr(f, 14)
        f["atr_ratio"] = f.atr / f.close
        f["threshold"] = f.atr_ratio.shift(1).rolling(720).quantile(0.4)
        f["prior_high"] = f.high.shift(1).rolling(48).max()
        return f

    def generate_long_entries(self, f) -> list[bool]:
        return (
            (f.ema50 > f.ema200)
            & (f.roc30 > 0)
            & (f.atr_ratio > f.threshold)
            & (f.close > f.prior_high)
            & (f.adx > self.parameters.adx_threshold)
        ).tolist()

    def generate_long_exits(self, f) -> list[bool]:
        return ((f.close < f.ema50) | (f.adx < 15) | (f.roc30 < 0)).tolist()
