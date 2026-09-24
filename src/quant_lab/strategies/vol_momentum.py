"""VOL_MOMENTUM_001: close-time momentum and EMA filter, long only."""

import numpy as np
import pandas as pd
from pydantic import Field

from quant_lab.config import StrictModel
from quant_lab.features import ema
from quant_lab.indicators import realized_volatility
from quant_lab.strategies._long_only import LongOnlyStrategy


class Parameters(StrictModel):
    lookback_days: int = Field(default=14, ge=1, le=180)


class VolMomentumStrategy(LongOnlyStrategy):
    name = "vol_momentum"
    parameter_model = Parameters

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        if self.config.market.timeframe != "1h":
            raise ValueError("Volatility momentum v1 requires 1h candles")
        result = candles.copy()
        result["momentum"] = (
            candles.close / candles.close.shift(self.parameters.lookback_days * 24) - 1
        )
        result["ema"] = ema(candles.close, 200)
        result["volatility"] = realized_volatility(
            candles.close, self.config.risk.volatility_period
        )
        return result

    def generate_long_entries(self, features) -> list[bool]:
        return (
            (features.momentum > 0)
            & (features.close > features.ema)
            & np.isfinite(features.volatility)
            & (features.volatility > 0)
        ).tolist()

    def generate_long_exits(self, features) -> list[bool]:
        return ((features.momentum <= 0) | (features.close < features.ema)).tolist()
