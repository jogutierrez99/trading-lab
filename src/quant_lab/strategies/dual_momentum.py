"""DUAL_MOMENTUM_001: compare raw cumulative ROC, without normalization."""

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
        if (self.short_days, self.long_days) not in {(7, 30), (14, 60), (7, 60)}:
            raise ValueError("Only the three frozen ROC pairs are permitted")
        return self


class DualMomentumStrategy(LongOnlyStrategy):
    name = "dual_momentum"
    parameter_model = Parameters

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        if self.config.market.timeframe != "1h":
            raise ValueError("Dual momentum v1 requires 1h data")
        f = candles.copy()
        f["ema200"] = ema(f.close, 200)
        f["roc_short"] = f.close / f.close.shift(self.parameters.short_days * 24) - 1
        f["roc_long"] = f.close / f.close.shift(self.parameters.long_days * 24) - 1
        return f

    def generate_long_entries(self, f) -> list[bool]:
        return (
            (f.close > f.ema200) & (f.roc_long > 0) & (f.roc_short > 0) & (f.roc_short > f.roc_long)
        ).tolist()

    def generate_long_exits(self, f) -> list[bool]:
        return ((f.roc_short < 0) | (f.roc_short < f.roc_long) | (f.close < f.ema200)).tolist()
