"""CHANNEL_BREAK_RETEST_001: frozen breakout, first retest, later confirmation."""

from typing import Literal

import pandas as pd

from quant_lab.config import StrictModel
from quant_lab.features import atr, ema
from quant_lab.setup_states import channel_retest
from quant_lab.strategies._long_only import LongOnlyStrategy


class Parameters(StrictModel):
    channel_hours: Literal[24, 48, 72] = 24


class ChannelBreakRetestStrategy(LongOnlyStrategy):
    name = "channel_break_retest"
    parameter_model = Parameters

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        if self.config.market.timeframe != "1h":
            raise ValueError("Channel retest v1 requires hourly data")
        f = candles.copy()
        f["ema50"] = ema(f.close, 50)
        f["ema200"] = ema(f.close, 200)
        f["atr"] = atr(f, 14)
        f["prior_high"] = f.high.shift(1).rolling(self.parameters.channel_hours).max()
        return f.join(channel_retest(f))

    def generate_long_entries(self, f) -> list[bool]:
        return f.entry.tolist()

    def generate_long_exits(self, f) -> list[bool]:
        return (f.close < f.ema50).tolist()
