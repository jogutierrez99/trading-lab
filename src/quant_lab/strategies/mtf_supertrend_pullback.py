"""supertrend_pullback: frozen causal V1/V2/V4 LONG_ONLY research signals."""

from quant_lab.new_mtf_strategy import NewMtfParameters, NewMtfStrategy


class Parameters(NewMtfParameters):
    """Indicator constants are frozen in new_mtf_features; no parameter grid."""


class MtfSupertrendPullbackStrategy(NewMtfStrategy):
    name = "mtf_supertrend_pullback"
    version = "1.0.0"
    parameter_model = Parameters
    family = "supertrend_pullback"
