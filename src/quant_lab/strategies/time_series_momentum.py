"""Hourly lagged momentum; execution controls exposure, not signals."""

import pandas as pd
from pydantic import Field

from quant_lab.config import StrictModel
from quant_lab.strategies.base import BaseStrategy


class Parameters(StrictModel):
    lookback_days: int = Field(default=14, ge=1, le=180)


class TimeSeriesMomentumStrategy(BaseStrategy[Parameters]):
    name = "time_series_momentum"
    version = "1.0.0"
    parameter_model = Parameters

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        if self.config.market.timeframe != "1h":
            raise ValueError("Momentum v1 requires 1h candles")
        result = candles.copy()
        n = self.parameters.lookback_days * 24
        result["momentum"] = candles.close.shift(1) / candles.close.shift(n + 1) - 1
        return result

    def generate_long_entries(self, features) -> list[bool]:
        return (features.momentum > 0).tolist()

    def generate_long_exits(self, features) -> list[bool]:
        return (features.momentum <= 0).tolist()

    def generate_short_entries(self, features) -> list[bool]:
        return (features.momentum < 0).tolist()

    def generate_short_exits(self, features) -> list[bool]:
        return (features.momentum >= 0).tolist()
