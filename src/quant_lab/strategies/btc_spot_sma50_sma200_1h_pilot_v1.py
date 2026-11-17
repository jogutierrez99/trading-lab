"""Close-time SMA50/SMA200 crossovers for the BTC spot pilot."""

from typing import Literal

import pandas as pd

from quant_lab.config import StrictModel
from quant_lab.features import sma
from quant_lab.strategies.base import BaseStrategy


class Parameters(StrictModel):
    fast_sma_period: Literal[50] = 50
    slow_sma_period: Literal[200] = 200


class BtcSpotSma50Sma2001hPilotV1Strategy(BaseStrategy[Parameters]):
    name = "btc_spot_sma50_sma200_1h_pilot_v1"
    version = "1.0.0"
    description = "Long-only hourly SMA50/SMA200 crossover with close-time signals"
    status = "experimental"
    created_at = "2026-11-16T22:59:28.663739+00:00"
    lab_timeframes = ("1h",)
    lab_modes = ("LONG_ONLY",)
    lab_execution = "ohlcv"
    parameter_model = Parameters

    @classmethod
    def required_warmup(cls, parameters: dict, timeframe: str) -> int:
        return 240

    def prepare_features(self, candles: pd.DataFrame) -> pd.DataFrame:
        features = candles.copy()
        features["fast_sma"] = sma(candles["close"], self.parameters.fast_sma_period)
        features["slow_sma"] = sma(candles["close"], self.parameters.slow_sma_period)
        return features

    def generate_long_entries(self, features: pd.DataFrame) -> list[bool]:
        fast = features["fast_sma"]
        slow = features["slow_sma"]
        return ((fast > slow) & (fast.shift(1) <= slow.shift(1))).tolist()

    def generate_long_exits(self, features: pd.DataFrame) -> list[bool]:
        fast = features["fast_sma"]
        slow = features["slow_sma"]
        return ((fast < slow) & (fast.shift(1) >= slow.shift(1))).tolist()

    def generate_short_entries(self, features: pd.DataFrame) -> list[bool]:
        return [False] * len(features)

    def generate_short_exits(self, features: pd.DataFrame) -> list[bool]:
        return [False] * len(features)
