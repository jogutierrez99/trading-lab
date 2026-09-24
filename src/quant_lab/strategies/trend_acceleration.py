"""TREND_ACCELERATION_001: slope acceleration lag stays fixed at 24 hours."""

from typing import Literal

import pandas as pd

from quant_lab.config import StrictModel
from quant_lab.features import ema
from quant_lab.strategies._long_only import LongOnlyStrategy


class Parameters(StrictModel):
    fast_hours: Literal[12, 24, 48] = 12


class TrendAccelerationStrategy(LongOnlyStrategy):
    name = "trend_acceleration"
    parameter_model = Parameters

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        if self.config.market.timeframe != "1h":
            raise ValueError("Trend acceleration v1 requires hourly data")
        f = candles.copy()
        f["ema50"] = ema(f.close, 50)
        f["ema200"] = ema(f.close, 200)
        f["slope_fast"] = f.ema50 / f.ema50.shift(self.parameters.fast_hours) - 1
        f["slope_slow"] = f.ema200 / f.ema200.shift(72) - 1
        f["previous_slope_fast"] = f.slope_fast.shift(24)
        f["prior_high"] = f.high.shift(1).rolling(24).max()
        return f

    def generate_long_entries(self, f) -> list[bool]:
        return (
            (f.ema50 > f.ema200)
            & (f.slope_fast > 0)
            & (f.slope_slow > 0)
            & (f.slope_fast > f.previous_slope_fast)
            & (f.close > f.prior_high)
        ).tolist()

    def generate_long_exits(self, f) -> list[bool]:
        return ((f.slope_fast < 0) | (f.ema50 < f.ema200)).tolist()
