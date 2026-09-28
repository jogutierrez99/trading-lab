"""BOLLINGER_REGIME_REVERSAL_001: symmetric, causal mean-reversion signals."""

from typing import Literal

import pandas as pd

from quant_lab.config import StrictModel
from quant_lab.features import atr, ema, rsi
from quant_lab.indicators import adx, bollinger
from quant_lab.strategies.base import BaseStrategy

VARIANTS = {
    "A": {"width": 2.0, "rsi_long": 30, "rsi_short": 70, "adx": 25, "stop_atr": 2.0},
    "B": {"width": 2.5, "rsi_long": 25, "rsi_short": 75, "adx": 25, "stop_atr": 2.0},
    "C": {"width": 2.0, "rsi_long": 35, "rsi_short": 65, "adx": 20, "stop_atr": 1.5},
}


class Parameters(StrictModel):
    variant: Literal["A", "B", "C"] = "A"
    trade_mode: Literal["LONG_ONLY", "SHORT_ONLY", "LONG_SHORT"] = "LONG_SHORT"


class BollingerRegimeReversalStrategy(BaseStrategy[Parameters]):
    lab_execution = "legacy_batch_006"
    name = "bollinger_regime_reversal"
    version = "1.0.0"
    parameter_model = Parameters

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        f = candles.copy().join(
            bollinger(candles.close, 20, VARIANTS[self.parameters.variant]["width"])
        )
        f["rsi"] = rsi(f.close, 14)
        f["adx"] = adx(f, 14)
        f["atr"] = atr(f, 14)
        f["ema200"] = ema(f.close, 200)
        f["distance_ema"] = (f.close - f.ema200).abs() / f.ema200
        return f

    def generate_long_entries(self, f) -> list[bool]:
        if self.parameters.trade_mode == "SHORT_ONLY":
            return [False] * len(f)
        p = VARIANTS[self.parameters.variant]
        return (
            (f.close < f.lower)
            & (f.rsi < p["rsi_long"])
            & (f.adx < p["adx"])
            & (f.distance_ema < 0.08)
        ).tolist()

    def generate_short_entries(self, f) -> list[bool]:
        if self.parameters.trade_mode == "LONG_ONLY":
            return [False] * len(f)
        p = VARIANTS[self.parameters.variant]
        return (
            (f.close > f.upper)
            & (f.rsi > p["rsi_short"])
            & (f.adx < p["adx"])
            & (f.distance_ema < 0.08)
        ).tolist()

    def generate_long_exits(self, f) -> list[bool]:
        return ((f.close >= f.middle) | (f.rsi >= 55)).tolist()

    def generate_short_exits(self, f) -> list[bool]:
        return ((f.close <= f.middle) | (f.rsi <= 45)).tolist()
