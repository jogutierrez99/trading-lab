"""RSI_MOMENTUM_RESET_001: single-use downward reset and upward recovery cross."""

from typing import Literal

import pandas as pd

from quant_lab.config import StrictModel
from quant_lab.features import ema, rsi
from quant_lab.setup_states import rsi_reset
from quant_lab.strategies._long_only import LongOnlyStrategy


class Parameters(StrictModel):
    reset_threshold: Literal[40, 35, 30] = 40


class RsiMomentumResetStrategy(LongOnlyStrategy):
    name = "rsi_momentum_reset"
    parameter_model = Parameters

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        if self.config.market.timeframe != "1h":
            raise ValueError("RSI momentum reset v1 requires hourly data")
        f = candles.copy()
        f["ema50"] = ema(f.close, 50)
        f["ema200"] = ema(f.close, 200)
        f["rsi"] = rsi(f.close, 14)
        f["roc30"] = f.close / f.close.shift(720) - 1
        return f.join(rsi_reset(f, self.parameters.reset_threshold))

    def generate_long_entries(self, f) -> list[bool]:
        return f.entry.tolist()

    def generate_long_exits(self, f) -> list[bool]:
        return ((f.rsi > 70) | (f.close < f.ema50) | (f.roc30 < 0)).tolist()
