"""Signal adapter for the new frozen LONG_ONLY research families."""

from functools import partial
from typing import Literal

import pandas as pd

from quant_lab.config import StrictModel
from quant_lab.mtf_features import STEPS, closed_features
from quant_lab.mtf_strategy import MtfStrategy
from quant_lab.new_mtf_features import (
    contiguous_features,
    higher_regime,
    hourly_event,
    v4_triggers,
)


class NewMtfParameters(StrictModel):
    architecture: Literal["V1", "V2", "V4"] = "V1"
    trade_mode: Literal["LONG_ONLY"] = "LONG_ONLY"


class NewMtfStrategy(MtfStrategy):
    lab_timeframes = ("1h", "15m")
    lab_modes = ("LONG_ONLY",)
    parameter_model = NewMtfParameters
    created_at = "2026-09-27T18:00:00Z"

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        tf = self.config.market.timeframe
        version = self.parameters.architecture
        if tf != ("15m" if version == "V4" else "1h"):
            raise ValueError(f"Invalid source timeframe for {version}")
        if candles.empty:
            return self._block(candles)
        groups = candles.index.to_series().diff().ne(STEPS[tf]).cumsum()
        return pd.concat([self._block(part) for _, part in candles.groupby(groups)])

    def _block(self, candles):
        tf, version = self.config.market.timeframe, self.parameters.architecture
        f = contiguous_features(candles, tf)
        hourly = (
            closed_features(candles, tf, "1h", partial(contiguous_features, tf="1h"))
            if version == "V4"
            else f
        )
        allowed = pd.Series(True, index=f.index)
        if version != "V1":
            higher = closed_features(candles, tf, "4h", partial(contiguous_features, tf="4h"))
            f["available_at_4h"] = higher.available_at
            allowed = higher_regime(higher, self.family).eq(True)
        f["risk_atr"] = hourly.atr
        if version == "V4":
            f["available_at_1h"] = hourly.available_at
            raw, confirmed, final, delay = v4_triggers(f, hourly, allowed, self.family)
        else:
            raw = confirmed = hourly_event(f, self.family).fillna(False)
            final = raw & allowed
            delay = f.st_touch_age if self.family == "supertrend_pullback" else float("nan")
        for key, value in (("raw", raw), ("confirmed", confirmed), ("final", final)):
            f[f"long_{key}"] = value
            f[f"short_{key}"] = False
        f["long_delay_hours"] = delay
        f["short_delay_hours"] = float("nan")
        return f
