"""MTF_MOMENTUM_001: confirmed 4h regime, hourly prior-high breakout."""

from typing import Literal

import pandas as pd

from quant_lab.config import StrictModel
from quant_lab.multitimeframe import confirmed_4h_features
from quant_lab.strategies._long_only import LongOnlyStrategy


class Parameters(StrictModel):
    breakout_hours: Literal[24, 48, 72] = 24


class MtfMomentumStrategy(LongOnlyStrategy):
    name = "mtf_momentum"
    parameter_model = Parameters

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        result = candles.copy().join(confirmed_4h_features(candles))
        result["prior_high"] = candles.high.shift(1).rolling(self.parameters.breakout_hours).max()
        return result

    def generate_long_entries(self, f) -> list[bool]:
        return (
            (f.htf_close > f.htf_ema200)
            & (f.htf_ema50 > f.htf_ema200)
            & (f.htf_momentum > 0)
            & (f.close > f.prior_high)
        ).tolist()

    def generate_long_exits(self, f) -> list[bool]:
        return (f.htf_ema50 < f.htf_ema200).tolist()
