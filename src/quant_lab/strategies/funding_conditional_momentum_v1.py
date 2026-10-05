"""Observed funding tails conditioned on momentum; four labelled continuation cases."""

from pydantic import Field

from quant_lab.config import StrictModel
from quant_lab.features import atr
from quant_lab.literature_features import LiteratureStrategy


class Parameters(StrictModel):
    momentum_lookback: int = Field(default=168, ge=2, le=2000)
    funding_window: int = Field(default=90, ge=10, le=1000)
    lower_quantile: float = Field(default=0.05, gt=0, lt=0.5, allow_inf_nan=False)
    atr_period: int = Field(default=14, ge=2, le=1000)
    stop_atr_multiplier: float = Field(default=2.0, gt=0, allow_inf_nan=False)


class FundingConditionalMomentumV1Strategy(LiteratureStrategy):
    name = "funding_conditional_momentum_v1"
    description = "Prior90-event funding tails5/95% + 7-day momentum; four labelled cases"
    lab_timeframes = ("1h",)
    lab_execution = "perpetual_funding"
    parameter_model = Parameters
    lab_risk_parameters = {"atr_period": "atr_period", "stop_atr_multiplier": "atr_multiplier"}

    @classmethod
    def required_warmup(cls, parameters, timeframe):
        cls.check_timeframe(timeframe)
        p = Parameters.model_validate(parameters)
        return max(p.momentum_lookback + 1, (p.funding_window + 1) * 8, p.atr_period + 1)

    def _features(self, candles):
        if not {
            "funding_rate",
            "funding_low",
            "funding_high",
            "funding_percentile",
            "funding_age_hours",
        } <= set(candles):
            raise ValueError("Observed causal funding inputs required; no invented funding")
        f = candles.copy()
        f["momentum"] = f.close / f.close.shift(self.parameters.momentum_lookback) - 1
        f["atr"] = atr(f, self.parameters.atr_period)
        f["ready"] = (
            f[["momentum", "atr", "funding_rate", "funding_low", "funding_high"]]
            .notna()
            .all(axis=1)
            & (f.atr > 0)
            & (f.funding_age_hours >= 0)
            & (f.funding_age_hours <= 8)
        )
        negative = (f.funding_rate < 0) & (f.funding_rate <= f.funding_low)
        positive = (f.funding_rate > 0) & (f.funding_rate >= f.funding_high)
        f["funding_extreme"] = negative | positive
        f["conditional_case"] = "neutral"
        for label, mask in (
            ("negative_positive", negative & (f.momentum > 0)),
            ("negative_negative", negative & (f.momentum < 0)),
            ("positive_negative", positive & (f.momentum < 0)),
            ("positive_positive", positive & (f.momentum > 0)),
        ):
            f.loc[mask, "conditional_case"] = label
        return f

    def _entries(self, f, side):
        return f.ready & f.funding_extreme & (f.momentum * side > 0)

    def _exits(self, f, side):
        return f.momentum * side <= 0
