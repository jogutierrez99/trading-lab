"""Backend-neutral, close-time strategy contract.

Frames supplied in future phases must contain only information available at each row.
Signals are decisions at candle close, never fills; earliest execution is next open.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol, cast

from quant_lab.config import StrategyConfig, StrictModel


class FeatureFrame(Protocol):
    """Minimal indexed frame contract, compatible with a future pandas backend."""

    def __len__(self) -> int: ...

    def __getitem__(self, key: str) -> Any: ...


@dataclass(frozen=True)
class Signals:
    long_entries: tuple[bool, ...]
    long_exits: tuple[bool, ...]
    short_entries: tuple[bool, ...]
    short_exits: tuple[bool, ...]


class BaseStrategy[P: StrictModel](ABC):
    name: ClassVar[str]
    version: ClassVar[str] = "1.0.0"
    description: ClassVar[str] = ""
    status: ClassVar[str] = "research"
    created_at: ClassVar[str | None] = None  # Unknown for legacy implementations.
    lab_timeframes: ClassVar[tuple[str, ...]] = ("1h",)
    lab_modes: ClassVar[tuple[str, ...]] = ("LONG_ONLY", "SHORT_ONLY", "LONG_SHORT")
    lab_execution: ClassVar[str] = "ohlcv"
    # Opt-in mapping only; execution and sizing remain in RiskConfig/StudyBackend.
    lab_risk_parameters: ClassVar[dict[str, str]] = {}
    lab_price_levels: ClassVar[bool] = False
    lab_extended_metrics: ClassVar[bool] = False
    lab_volatility_timeframes: ClassVar[tuple[str, ...]] = ("1h",)
    lab_entry_diagnostics: ClassVar[bool] = False
    parameter_model: ClassVar[type[StrictModel]]

    @classmethod
    def required_warmup(cls, parameters: dict, timeframe: str) -> int:
        return 0

    def entry_levels(self, candles: FeatureFrame):
        """Opt-in absolute stops/targets known at each signal close, never fills."""
        return None

    def __init__(self, config: StrategyConfig):
        if config.name != self.name or config.version != self.version:
            raise ValueError("Configuration strategy name/version does not match implementation")
        self.config = config.model_copy(deep=True)
        self.parameters = self.validate_parameters()

    def validate_parameters(self) -> P:
        return cast(P, self.parameter_model.model_validate(self.config.parameters))

    def metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "parameters": self.parameters.model_dump(mode="json"),
        }

    @abstractmethod
    def prepare_features(self, candles: FeatureFrame) -> FeatureFrame: ...

    @abstractmethod
    def generate_long_entries(self, features: FeatureFrame) -> Sequence[bool]: ...

    @abstractmethod
    def generate_long_exits(self, features: FeatureFrame) -> Sequence[bool]: ...

    @abstractmethod
    def generate_short_entries(self, features: FeatureFrame) -> Sequence[bool]: ...

    @abstractmethod
    def generate_short_exits(self, features: FeatureFrame) -> Sequence[bool]: ...

    def generate_signals(self, candles: FeatureFrame) -> Signals:
        features = self.prepare_features(candles)
        if len(features) != len(candles):
            raise ValueError("Features must preserve input row count and order")
        outputs = [
            tuple(method(features))
            for method in (
                self.generate_long_entries,
                self.generate_long_exits,
                self.generate_short_entries,
                self.generate_short_exits,
            )
        ]
        for values in outputs:
            if len(values) != len(candles) or any(type(v) is not bool for v in values):
                raise ValueError("Signals must contain one Python bool per input row")
        return Signals(*outputs)
