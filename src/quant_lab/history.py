"""Strict historical data requests; independent of strategy and execution settings."""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field, model_validator

from quant_lab.config import StrictModel


class HistoryRequest(StrictModel):
    provider: Literal["binance"] = "binance"
    market_type: Literal["spot"] = "spot"
    symbol: str = Field(default="BTC/USDT", pattern=r"^[A-Z0-9]+/[A-Z0-9]+$")
    timeframe: Literal["1h"] = "1h"
    start: datetime
    end: datetime
    warmup_bars: int = Field(default=200, ge=0, le=10000)

    @model_validator(mode="after")
    def validate_range(self) -> "HistoryRequest":
        for value in (self.start, self.end):
            if value.utcoffset() != timedelta(0):
                raise ValueError("Dates must be timezone-aware UTC")
            if value.minute or value.second or value.microsecond:
                raise ValueError("Dates must align to full hours")
        if self.start >= self.end:
            raise ValueError("start must precede exclusive end")
        return self

    @property
    def download_start(self) -> datetime:
        return self.start - timedelta(hours=self.warmup_bars)
