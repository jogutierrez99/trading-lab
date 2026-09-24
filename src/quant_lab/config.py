"""Strict YAML configuration. Cost and risk fields ending in pct use percentages."""

from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


StrategyName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")]
Version = Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
Percentage = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]


class MarketConfig(StrictModel):
    provider: str = "binance"
    symbol: str = Field(default="BTC/USDT", pattern=r"^[A-Z0-9]+/[A-Z0-9]+$")
    timeframe: str = Field(default="1h", pattern=r"^[1-9][0-9]*[mhdw]$")


class CostsConfig(StrictModel):
    trading_fee_pct: Percentage = 0.05
    slippage_pct: Percentage = 0.03
    spread_pct: Percentage = 0.01


class RiskConfig(StrictModel):
    risk_per_trade_pct: float = Field(default=1.0, gt=0, le=100, allow_inf_nan=False)
    max_position_pct: float = Field(default=25.0, gt=0, le=100, allow_inf_nan=False)
    max_exposure_pct: float = Field(default=100.0, gt=0, le=100, allow_inf_nan=False)
    stop_method: Literal["atr", "structure", "sweep"] = "atr"
    atr_multiplier: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    risk_reward: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    atr_period: int = Field(default=14, ge=1)
    sizing_method: Literal["stop_risk", "fixed_notional", "volatility_target"] = "stop_risk"
    position_pct: float = Field(default=25.0, gt=0, le=100, allow_inf_nan=False)
    stop_enabled: bool = True
    take_profit_enabled: bool = True
    trailing_atr_multiplier: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    max_holding_bars: int | None = Field(default=None, ge=1)
    trailing_basis: Literal["high_low", "close"] = "high_low"
    volatility_period: int = Field(default=720, ge=2)
    target_volatility_pct: float = Field(default=20.0, gt=0, allow_inf_nan=False)
    min_position_pct: float = Field(default=5.0, gt=0, le=100, allow_inf_nan=False)

    @model_validator(mode="after")
    def check_exposure(self) -> "RiskConfig":
        if self.max_position_pct > self.max_exposure_pct:
            raise ValueError("max_position_pct cannot exceed max_exposure_pct")
        if self.sizing_method == "volatility_target" and self.min_position_pct > min(
            self.max_position_pct, self.max_exposure_pct
        ):
            raise ValueError("Minimum volatility-scaled exposure exceeds maximum")
        if not self.stop_enabled and (
            self.sizing_method == "stop_risk"
            or self.take_profit_enabled
            or self.trailing_atr_multiplier is not None
        ):
            raise ValueError("Disabled stop requires fixed_notional, no target and no trailing")
        return self


class StrategyConfig(StrictModel):
    name: StrategyName
    version: Version = "1.0.0"
    enabled: bool = False
    market: MarketConfig = Field(default_factory=MarketConfig)
    parameters: dict[str, Any] = Field(default_factory=dict)
    risk: RiskConfig = Field(default_factory=RiskConfig)


class AppConfig(StrictModel):
    schema_version: Literal[1] = 1
    mode: Literal["research"] = "research"
    starting_capital: float = Field(default=10000.0, gt=0, allow_inf_nan=False)
    random_seed: int = Field(default=42, ge=0)
    costs: CostsConfig = Field(default_factory=CostsConfig)
    markets_file: str = "markets.yaml"
    risk_file: str = "risk.yaml"
    strategies_dir: str = "strategies"


class MarketsConfig(StrictModel):
    markets: list[MarketConfig] = Field(min_length=1)


class ResearchConfig(StrictModel):
    app: AppConfig
    markets: MarketsConfig
    risk: RiskConfig
    strategies: tuple[StrategyConfig, ...]


class ConfigurationError(ValueError):
    """A configuration file could not be read or validated."""


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys instead of silently taking the last value."""


def _unique_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode) -> dict:
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in mapping:
            raise ValueError(f"Duplicate YAML key: {key!r}")
        mapping[key] = loader.construct_object(value_node)
    return mapping


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _read_mapping(path: Path) -> dict[str, Any]:
    raw = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    if not isinstance(raw, dict):
        raise ValueError("Expected a YAML mapping")
    return raw


def load_yaml[T: BaseModel](path: str | Path, model: type[T]) -> T:
    path = Path(path)
    try:
        return model.model_validate(_read_mapping(path))
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"{path}: {exc}") from exc


def load_research_config(path: str | Path) -> ResearchConfig:
    """Resolve referenced files relative to app.yaml, independent of working directory.

    A strategy's explicit risk fields override risk.yaml; remaining fields inherit it.
    Strategy-specific parameter validation occurs when the registry creates a strategy.
    """
    path = Path(path).resolve()
    app = load_yaml(path, AppConfig)
    risk = load_yaml(path.parent / app.risk_file, RiskConfig)
    directory = path.parent / app.strategies_dir
    if not directory.is_dir():
        raise ConfigurationError(f"Strategy configuration directory does not exist: {directory}")
    strategies = []
    for file in sorted(directory.glob("*.yaml")):
        try:
            raw = _read_mapping(file)
            overrides = raw.get("risk", {})
            if not isinstance(overrides, dict):
                raise ValueError("Strategy risk must be a mapping")
            raw["risk"] = risk.model_dump() | overrides
            strategies.append(StrategyConfig.model_validate(raw))
        except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
            raise ConfigurationError(f"{file}: {exc}") from exc
    names = [strategy.name for strategy in strategies]
    if len(set(names)) != len(names):
        raise ConfigurationError("Duplicate strategy names in configuration directory")
    return ResearchConfig(
        app=app,
        markets=load_yaml(path.parent / app.markets_file, MarketsConfig),
        risk=risk,
        strategies=tuple(strategies),
    )
