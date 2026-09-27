"""trend_pullback: shared V1-V4 causal signal components, frozen rules."""

from quant_lab.mtf_strategy import MtfParameters, MtfStrategy


class Parameters(MtfParameters):
    """Only architecture and direction are configurable; no parameter search."""


class MtfTrendPullbackStrategy(MtfStrategy):
    name = "mtf_trend_pullback"
    version = "1.0.0"
    parameter_model = Parameters
    family = "trend_pullback"
