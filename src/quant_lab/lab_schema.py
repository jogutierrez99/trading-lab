"""Strict, offline experiment definitions. All relative paths are YAML-relative."""

from datetime import datetime, timedelta
from itertools import product
from math import prod
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from quant_lab.config import CostsConfig, StrategyName, StrictModel, load_yaml
from quant_lab.execution_config import ExecutionConfig

Mode = Literal["LONG_ONLY", "SHORT_ONLY", "LONG_SHORT"]
Metric = Literal["return_pct", "sharpe", "profit_factor", "closed_trades", "max_drawdown_pct"]


class Period(StrictModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def ordered(self):
        if any(t.utcoffset() != timedelta(0) for t in (self.start, self.end)):
            raise ValueError("Period boundaries must be timezone-aware UTC")
        if self.start >= self.end:
            raise ValueError("Period start must precede exclusive end")
        return self


class Fold(StrictModel):
    train: Period
    test: Period

    @model_validator(mode="after")
    def causal(self):
        if self.train.end > self.test.start:
            raise ValueError("Walk-forward training must end before test")
        return self


class Validation(StrictModel):
    train: Period
    validation: Period
    test: Period
    walk_forward: list[Fold] = Field(default_factory=list)
    cost_stress: dict[StrategyName, CostsConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def causal(self):
        if self.train.end > self.validation.start or self.validation.end > self.test.start:
            raise ValueError("Require disjoint chronological train, validation and test")
        if "base" in self.cost_stress:
            raise ValueError("Cost scenario 'base' is reserved")
        previous = None
        for fold in self.walk_forward:
            if fold.test.end > self.test.start:
                raise ValueError("Walk-forward must precede the final holdout test")
            if previous is not None and fold.test.start < previous:
                raise ValueError("Walk-forward test periods must be ordered and disjoint")
            previous = fold.test.end
        return self

    def periods(self):
        yield "train", self.train
        yield "validation", self.validation
        yield "test", self.test
        for index, fold in enumerate(self.walk_forward):
            yield f"wf_{index}_train", fold.train
            yield f"wf_{index}_test", fold.test


class Auxiliary(StrictModel):
    dataset: str = Field(min_length=1)
    dataset_id: str = Field(pattern=r"^[a-f0-9]{64}$")


class PerpetualLabExecution(ExecutionConfig):
    """Only the explicit funding adapter accepts this specialized lab execution."""

    market_mode: Literal["perpetual"] = "perpetual"


class Market(StrictModel):
    symbol: Literal["BTCUSDT", "ETHUSDT"]
    timeframe: Literal["15m", "1h", "4h", "1d"]
    dataset: str = Field(min_length=1)
    dataset_format: Literal["bundle", "mtf_quarters"] = "bundle"
    dataset_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    warmup_bars: int = Field(default=200, ge=0, le=10000)
    perpetual_data: Auxiliary | None = None

    @model_validator(mode="after")
    def source_contract(self):
        if self.timeframe == "15m" and self.dataset_format != "mtf_quarters":
            raise ValueError("Lab 15m currently requires explicit mtf_quarters dataset format")
        if self.dataset_format == "mtf_quarters" and (
            self.timeframe != "15m" or self.dataset_id is None
        ):
            raise ValueError("mtf_quarters requires 15m and an explicit dataset_id")
        return self


class Strategy(StrictModel):
    id: StrategyName
    config: str = Field(min_length=1)


class Filters(StrictModel):
    minimum_trades: int = Field(default=1, ge=0)
    maximum_drawdown_pct: float = Field(default=100.0, ge=0, le=100, allow_inf_nan=False)
    minimum_profit_factor: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    minimum_sharpe: float | None = Field(default=None, allow_inf_nan=False)
    positive_test: bool = False
    cost_stress_survival: bool = False


class Ranking(StrictModel):
    metric: Metric = "sharpe"
    descending: bool = True
    top_n: int = Field(default=10, ge=1, le=50)


class Experiment(StrictModel):
    schema_version: Literal[1] = 1
    experiment_id: StrategyName
    created_at: datetime
    description: str = Field(min_length=1)
    app: str = "../app.yaml"
    strategy: Strategy
    markets: list[Market] = Field(min_length=1)
    modes: list[Mode] = Field(default_factory=lambda: ["LONG_ONLY"], min_length=1)
    strategy_parameters: dict[str, list[Any]] = Field(default_factory=dict)
    initial_cash: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    costs: CostsConfig | None = None
    execution: ExecutionConfig | PerpetualLabExecution
    validation: Validation
    diagnostic_periods: dict[StrategyName, Period] = Field(default_factory=dict)
    filters: Filters = Field(default_factory=Filters)
    ranking: Ranking = Field(default_factory=Ranking)

    @model_validator(mode="after")
    def consistent(self):
        previous = None
        for label, period in self.diagnostic_periods.items():
            if not label.startswith("diagnostic_"):
                raise ValueError("Diagnostic labels must start with diagnostic_")
            if period.start < self.validation.train.start or period.end > self.validation.test.end:
                raise ValueError("Diagnostics must lie within the research coverage")
            if previous is not None and period.start < previous:
                raise ValueError("Diagnostic periods must be ordered and disjoint")
            previous = period.end
        if self.created_at.utcoffset() != timedelta(0):
            raise ValueError("created_at must be timezone-aware UTC")
        keys = [(m.symbol, m.timeframe) for m in self.markets]
        if len(keys) != len(set(keys)) or len(self.modes) != len(set(self.modes)):
            raise ValueError("Duplicate markets or modes")
        if any(not values for values in self.strategy_parameters.values()):
            raise ValueError("Parameter grids must not be empty")
        if self.combinations > 100000:
            raise ValueError("Grid exceeds 100000 combinations; split the experiment")
        if not self.execution.liquidate_at_end:
            raise ValueError("Independent research periods require liquidate_at_end")
        if self.execution.direction != "long":
            raise ValueError("Use modes for directions; execution.direction must stay 'long'")
        if self.execution.market_mode == "spot" and self.modes != ["LONG_ONLY"]:
            raise ValueError("SHORT modes require explicit synthetic execution (no funding)")
        if self.filters.cost_stress_survival and not self.validation.cost_stress:
            raise ValueError("cost_stress_survival requires cost_stress scenarios")
        return self

    @property
    def combinations(self):
        return prod(len(values) for values in self.strategy_parameters.values())

    def periods(self):
        yield from experiment_periods(self)

    def grid(self):
        keys = sorted(self.strategy_parameters)
        for values in product(*(self.strategy_parameters[key] for key in keys)):
            yield dict(zip(keys, values, strict=True))


def experiment_periods(experiment):
    """Shared preparation also accepts frozen challenge protocols without diagnostics."""
    yield from experiment.validation.periods()
    yield from getattr(experiment, "diagnostic_periods", {}).items()


def discover(directory: Path) -> dict[str, tuple[Path, Experiment]]:
    found = {}
    for path in sorted(directory.glob("*.yaml")):
        experiment = load_yaml(path, Experiment)
        if experiment.experiment_id in found:
            raise ValueError(f"Duplicate experiment_id: {experiment.experiment_id}")
        found[experiment.experiment_id] = (path.resolve(), experiment)
    return found


def resolve(directory: Path, name: str) -> tuple[Path, Experiment]:
    found = discover(directory)
    if name == "latest-experiment" and found:
        name = max(found, key=lambda key: (found[key][1].created_at, key))
    if name not in found:
        raise ValueError(f"Unknown experiment: {name}; use 'experiments' to list definitions")
    return found[name]
