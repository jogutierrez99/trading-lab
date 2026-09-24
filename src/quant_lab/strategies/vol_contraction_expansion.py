"""VOL_CONTRACTION_EXPANSION_001: past contraction count precedes expansion."""

from typing import Literal

import pandas as pd

from quant_lab.config import StrictModel
from quant_lab.features import atr, ema
from quant_lab.strategies._long_only import LongOnlyStrategy


class Parameters(StrictModel):
    contraction_bars: Literal[6, 12, 18] = 6


class VolContractionExpansionStrategy(LongOnlyStrategy):
    name = "vol_contraction_expansion"
    parameter_model = Parameters

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        if self.config.market.timeframe != "1h":
            raise ValueError("Vol contraction expansion v1 requires hourly data")
        f = candles.copy()
        f["ema50"] = ema(f.close, 50)
        f["ema200"] = ema(f.close, 200)
        f["roc7"] = f.close / f.close.shift(168) - 1
        f["atr"] = atr(f, 14)
        f["atr_ratio"] = f.atr / f.close
        previous = f.atr_ratio.shift(1).rolling(720)
        f["p30"] = previous.quantile(0.3)
        f["p50"] = previous.quantile(0.5)
        f["contraction"] = (f.atr_ratio < f.p30).astype(float).where(f.p30.notna())
        f["recent_contractions"] = f.contraction.shift(1).rolling(24).sum()
        f["previous_ratio"] = f.atr_ratio.shift(1)
        f["prior_high"] = f.high.shift(1).rolling(24).max()
        return f

    def generate_long_entries(self, f) -> list[bool]:
        return (
            (f.recent_contractions >= self.parameters.contraction_bars)
            & (f.atr_ratio > f.p50)
            & (f.atr_ratio > f.previous_ratio)
            & (f.ema50 > f.ema200)
            & (f.roc7 > 0)
            & (f.close > f.prior_high)
        ).tolist()

    def generate_long_exits(self, f) -> list[bool]:
        return ((f.close < f.ema50) | (f.roc7 < 0) | (f.atr_ratio < f.p30)).tolist()
