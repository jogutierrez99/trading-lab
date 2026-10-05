"""Own-return momentum and capped causal entry-time volatility scaling."""

import pandas as pd
from pydantic import Field

from quant_lab.config import StrictModel
from quant_lab.features import ema
from quant_lab.indicators import realized_volatility
from quant_lab.literature_features import LiteratureStrategy
from quant_lab.study_data import HOURS


class Parameters(StrictModel):
    ema_period: int = Field(default=200, ge=2, le=1000)
    momentum_lookback: int = Field(default=180, ge=2, le=5000)
    volatility_period: int = Field(default=180, ge=2, le=5000)
    target_volatility_pct: float = Field(default=10.0, gt=0, allow_inf_nan=False)


class RiskManagedMomentumV1Strategy(LiteratureStrategy):
    name = "risk_managed_momentum_v1"
    description = "30-day own return + EMA200; entry-time capped inverse-volatility exposure"
    lab_timeframes = ("4h", "1d")
    lab_volatility_timeframes = ("4h", "1d")
    parameter_model = Parameters
    lab_risk_parameters = {
        "volatility_period": "volatility_period",
        "target_volatility_pct": "target_volatility_pct",
    }

    @classmethod
    def required_warmup(cls, parameters, timeframe):
        cls.check_timeframe(timeframe)
        p = Parameters.model_validate(parameters)
        return max(5 * p.ema_period, p.momentum_lookback + 1, p.volatility_period + 1)

    def _features(self, candles):
        p = self.parameters
        f = candles.copy()
        f["ema"] = ema(f.close, p.ema_period)
        f["momentum"] = f.close / f.close.shift(p.momentum_lookback) - 1
        f["realized_volatility"] = realized_volatility(
            f.close, p.volatility_period, annual_bars=365 * 24 / HOURS[self.config.market.timeframe]
        )
        f["ready"] = (
            (pd.Series(range(1, len(f) + 1), index=f.index) >= 5 * p.ema_period)
            & f[["ema", "momentum", "realized_volatility"]].notna().all(axis=1)
            & (f.realized_volatility > 0)
        )
        return f

    def _entries(self, f, side):
        return f.ready & (f.momentum * side > 0) & ((f.close - f.ema) * side > 0)

    def _exits(self, f, side):
        return f.ready & (f.momentum * side <= 0)
