"""Historical execution assumptions, separate from strategy parameters."""

from typing import Literal

from pydantic import Field, model_validator

from quant_lab.config import StrictModel


class ExecutionConfig(StrictModel):
    market_mode: Literal["spot", "synthetic"] = "spot"
    direction: Literal["long", "short", "combined"] = "long"
    quantity_step: float = Field(gt=0, allow_inf_nan=False)
    min_quantity: float = Field(ge=0, allow_inf_nan=False)
    min_notional: float = Field(ge=0, allow_inf_nan=False)
    filter_assumption: str = Field(min_length=1)
    liquidate_at_end: bool = True

    @model_validator(mode="after")
    def check_spot(self) -> "ExecutionConfig":
        if self.market_mode == "spot" and self.direction != "long":
            raise ValueError("Spot supports long only; shorts require explicit synthetic research")
        return self
