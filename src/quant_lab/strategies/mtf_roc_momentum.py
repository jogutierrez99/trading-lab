"""roc_momentum: frozen causal V1/V2/V4 LONG_ONLY research signals."""

from quant_lab.new_mtf_strategy import NewMtfParameters, NewMtfStrategy


class Parameters(NewMtfParameters):
    """Indicator constants are frozen in new_mtf_features; no parameter grid."""


class MtfRocMomentumStrategy(NewMtfStrategy):
    name = "mtf_roc_momentum"
    version = "1.0.0"
    parameter_model = Parameters
    family = "roc_momentum"
