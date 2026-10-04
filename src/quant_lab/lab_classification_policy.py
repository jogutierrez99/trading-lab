"""Versioned, explicit economic gates; unrelated to historical legacy filters."""

from typing import Literal

from pydantic import Field, model_validator

from quant_lab.config import StrategyName, StrictModel


class MetricGate(StrictModel):
    minimum_trades: int = Field(default=1, ge=1)
    minimum_profit_factor: float = Field(default=1.0, ge=0, allow_inf_nan=False)
    minimum_sharpe: float | None = Field(default=None, allow_inf_nan=False)
    minimum_expectancy: float = Field(default=0.0, allow_inf_nan=False)
    expectancy_strict: bool = False
    minimum_return_pct: float | None = Field(default=None, allow_inf_nan=False)
    return_strict: bool = False
    maximum_drawdown_pct: float = Field(default=100.0, ge=0, le=100, allow_inf_nan=False)


class RobustGate(StrictModel):
    required_folds: int = Field(default=4, ge=1)
    positive_return_folds: int = Field(default=3, ge=1)
    nonnegative_expectancy_folds: int = Field(default=3, ge=1)
    positive_adverse_folds: int = Field(default=2, ge=1)
    aggregation: Literal["median"] = "median"

    @model_validator(mode="after")
    def counts(self):
        if (
            max(
                self.positive_return_folds,
                self.nonnegative_expectancy_folds,
                self.positive_adverse_folds,
            )
            > self.required_folds
        ):
            raise ValueError("Fold minimum exceeds required_folds")
        return self


class ClassificationPolicy(StrictModel):
    classification_schema_version: Literal[1] = 1
    policy_id: StrategyName
    adverse_scenario: StrategyName = "adverse"
    train: MetricGate
    validation: MetricGate
    validation_adverse: MetricGate
    test: MetricGate
    test_adverse: MetricGate
    robustness: RobustGate = Field(default_factory=RobustGate)
    minimum_total_oos_trades: int = Field(default=30, ge=1)

    @model_validator(mode="after")
    def distinct_costs(self):
        if self.adverse_scenario == "base":
            raise ValueError("Adverse scenario cannot be base")
        return self
