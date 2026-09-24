"""BB_SQUEEZE_001: breakout after a fully historical compression window."""

import pandas as pd
from pydantic import Field

from quant_lab.config import StrictModel
from quant_lab.features import ema
from quant_lab.indicators import bollinger
from quant_lab.strategies._long_only import LongOnlyStrategy


class Parameters(StrictModel):
    squeeze_percentile_pct: float = Field(default=20.0, gt=0, lt=100, allow_inf_nan=False)


class BbSqueezeStrategy(LongOnlyStrategy):
    name = "bb_squeeze"
    parameter_model = Parameters

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        result = candles.copy().join(bollinger(candles.close))
        result["ema"] = ema(candles.close, 200)
        result["threshold"] = (
            result.bandwidth.shift(1)
            .rolling(720)
            .quantile(self.parameters.squeeze_percentile_pct / 100)
        )
        result["squeeze"] = (
            (result.bandwidth < result.threshold).astype(float).where(result.threshold.notna())
        )
        result["recent_squeeze"] = result["squeeze"].shift(1).rolling(24).max()
        return result

    def generate_long_entries(self, features) -> list[bool]:
        return (
            (features.recent_squeeze > 0)
            & (features.close > features.upper)
            & (features.close > features.ema)
        ).tolist()

    def generate_long_exits(self, features) -> list[bool]:
        return (features.close < features.middle).tolist()
