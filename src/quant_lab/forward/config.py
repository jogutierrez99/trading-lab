"""Forward configuration deliberately separate from historical experiment schemas."""

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from quant_lab.brokers.okx_demo import safety_environment
from quant_lab.config import CostsConfig, RiskConfig, StrictModel, load_yaml
from quant_lab.mtf_execution import Settings

RMM_NAMES = [
    "rmm_eth_long_short_4h",
    "rmm_eth_long_only_4h",
    "rmm_btc_long_short_4h",
    "rmm_btc_long_only_4h_shadow",
]


class RMMSettings(StrictModel):
    capital: Literal[10000.0] = 10000.0
    risk: RiskConfig = RiskConfig(
        sizing_method="volatility_target",
        stop_enabled=False,
        take_profit_enabled=False,
        volatility_period=180,
        target_volatility_pct=10.0,
    )
    costs: dict[str, CostsConfig] = {"base": CostsConfig()}


class ForwardConfig(StrictModel):
    data_protocol: Literal["eth_v1_required_1h_15m", "rmm_4h"] = "eth_v1_required_1h_15m"
    environment: Literal["demo"] = "demo"
    mode: Literal["signal_only"] = "signal_only"
    broker: Literal["okx"] = "okx"
    trading_enabled: Literal[False] = False
    allow_live_trading: Literal[False] = False
    instruments: dict[str, str]
    strategies: list[str]
    demo_strategy: str = "rmm_eth_long_short_4h"
    parameters: dict[str, int | float] = {
        "ema_period": 200,
        "momentum_lookback": 180,
        "volatility_period": 180,
        "target_volatility_pct": 10.0,
    }
    inherited_profile: str = "../profiles/mtf_series.yaml"
    output: str = "../../results/forward"
    warmup_bars: int = Field(default=800, ge=250, le=5000)
    heartbeat_seconds: int = Field(default=30, ge=10, le=120)
    max_reconnects: int = Field(default=8, ge=0, le=100)

    def required_feed(self, instrument, timeframe):
        if self.data_protocol == "rmm_4h":
            return instrument in self.instruments.values() and timeframe == "4h"
        # Future architectures must declare dependencies before being admitted.
        return instrument == self.instruments["ETH"] and timeframe in {"1h", "15m"}

    @model_validator(mode="after")
    def validate_scope(self):
        if self.data_protocol == "rmm_4h":
            assets = set(self.instruments)
            expected_strategies = RMM_NAMES if assets == {"ETH", "BTC"} else RMM_NAMES[2:]
            if (
                assets not in ({"ETH", "BTC"}, {"BTC"})
                or self.strategies != expected_strategies
                or self.demo_strategy not in set(expected_strategies) & set(RMM_NAMES[:3])
                or self.parameters
                != dict(
                    ema_period=200,
                    momentum_lookback=180,
                    volatility_period=180,
                    target_volatility_pct=10.0,
                )
                or self.warmup_bars < 1000
                or any(v != "AUTO" for v in self.instruments.values())
            ):
                raise ValueError(
                    "RMM requires the frozen ETH/BTC or BTC-only alternatives, "
                    "a selected MAIN, AUTO discovery and warmup1000"
                )
            return self
        if self.instruments != {"ETH": "ETH-USD_UM_XPERP-310328", "BTC": "BTC-USD_UM_XPERP-310328"}:
            raise ValueError("This phase is pinned to the two requested OKX EU instruments")
        if not self.strategies or len(set(self.strategies)) != len(self.strategies):
            raise ValueError("Strategies must be nonempty and unique")
        if any(
            s not in {"eth_trend_pullback_v1", "eth_trend_pullback_v1_optional_15m_fill"}
            for s in self.strategies
        ):
            raise ValueError("Unsupported legacy strategy")
        return self


def load_config(path):
    safety_environment()
    path = Path(path).resolve()
    config = load_yaml(path, ForwardConfig)
    if config.data_protocol == "rmm_4h":
        return config, RMMSettings(), (path.parent / config.output).resolve()
    inherited = load_yaml(path.parent / config.inherited_profile, Settings)
    risk = inherited.risk
    if (
        risk.risk_per_trade_pct,
        risk.max_position_pct,
        risk.max_exposure_pct,
        risk.atr_multiplier,
        risk.max_holding_bars,
        risk.take_profit_enabled,
    ) != (0.5, 25, 25, 2, 72, False):
        raise ValueError("Inherited frozen risk protocol changed; review required")
    return config, inherited, (path.parent / config.output).resolve()
