"""Shared signal-only architecture; no execution or historical-result selection."""

from abc import abstractmethod
from typing import Literal

import pandas as pd

from quant_lab.config import StrictModel
from quant_lab.mtf_features import (
    STEPS,
    base_setup,
    closed_features,
    confirmation,
    features,
    regime,
    trigger,
)
from quant_lab.strategies.base import BaseStrategy


class MtfParameters(StrictModel):
    architecture: Literal["V1", "V2", "V3", "V4"] = "V1"
    trade_mode: Literal["LONG_ONLY", "SHORT_ONLY", "LONG_SHORT"] = "LONG_ONLY"


class MtfStrategy(BaseStrategy[MtfParameters]):
    lab_execution = "legacy_mtf"
    parameter_model = MtfParameters

    @property
    @abstractmethod
    def family(self) -> str: ...

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        version = self.parameters.architecture
        tf = self.config.market.timeframe
        expected = "15m" if version in {"V3", "V4"} else "1h"
        if tf != expected:
            raise ValueError(f"{version} requires {expected} source bars")
        f = features(candles)
        higher = closed_features(candles, tf, "4h") if version != "V1" else None
        hourly = closed_features(candles, tf, "1h") if tf == "15m" else f
        f["risk_atr"] = hourly.atr
        if higher is not None:
            f["available_at_4h"] = higher.available_at
        if tf == "15m":
            f["available_at_1h"] = hourly.available_at
        for side in ("long", "short"):
            raw = trigger(f, self.family, side, version)
            setup = (
                base_setup(f, self.family, side)
                if version in {"V1", "V2"}
                else confirmation(hourly, self.family, side, version)
            )
            allowed = (
                regime(higher, self.family, side)
                if higher is not None
                else pd.Series(True, index=f.index)
            )
            f[f"{side}_raw"] = raw.fillna(False)
            f[f"{side}_confirmed"] = (raw & setup).fillna(False)
            f[f"{side}_final"] = (raw & setup & allowed).fillna(False)
            age = f[f"{side}_{'middle' if self.family == 'bollinger' else 'ema'}_touch_age"]
            f[f"{side}_delay_hours"] = age * STEPS[tf].total_seconds() / 3600
        return f

    def generate_long_entries(self, f) -> list[bool]:
        return (
            f.long_final.tolist()
            if self.parameters.trade_mode != "SHORT_ONLY"
            else [False] * len(f)
        )

    def generate_short_entries(self, f) -> list[bool]:
        return (
            f.short_final.tolist()
            if self.parameters.trade_mode != "LONG_ONLY"
            else [False] * len(f)
        )

    def generate_long_exits(self, f) -> list[bool]:
        return [False] * len(f)

    def generate_short_exits(self, f) -> list[bool]:
        return [False] * len(f)
