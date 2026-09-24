"""Cost-aware sizing and fixed protective levels; no strategy decisions."""

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from math import isfinite

from quant_lab.config import CostsConfig, RiskConfig
from quant_lab.execution_config import ExecutionConfig


@dataclass(frozen=True)
class CostModel:
    fee: float
    adverse: float

    @classmethod
    def from_config(cls, config: CostsConfig) -> "CostModel":
        result = cls(
            config.trading_fee_pct / 100, (config.slippage_pct + config.spread_pct / 2) / 100
        )
        if result.fee >= 1 or result.adverse >= 1:
            raise ValueError("Execution requires fee and adverse price adjustment below 100%")
        return result

    def price(self, reference: float, order_side: int) -> float:
        return reference * (1 + order_side * self.adverse)


@dataclass(frozen=True)
class SizedEntry:
    price: float
    quantity: float
    stop: float | None
    target: float | None
    entry_fee: float
    risk_budget: float | None
    expected_stop_loss: float | None


def size_entry(
    equity: float,
    opening: float,
    distance: float,
    side: int,
    risk: RiskConfig,
    execution: ExecutionConfig,
    costs: CostModel,
) -> SizedEntry | str:
    if risk.stop_enabled and (not isfinite(distance) or distance <= 0):
        return "invalid_stop_distance"
    if equity <= 0:
        return "insufficient_equity"
    entry = costs.price(opening, side)
    stop = entry - side * distance if risk.stop_enabled else None
    target = entry + side * distance * risk.risk_reward if risk.take_profit_enabled else None
    levels = [v for v in (entry, stop, target) if v is not None]
    if min(levels) <= 0 or not all(isfinite(v) for v in levels):
        return "invalid_protective_levels"
    loss_per_unit = None
    if stop is not None:
        stop_fill = costs.price(stop, -side)
        loss_per_unit = side * (entry - stop_fill) + costs.fee * (entry + stop_fill)
    budget = equity * risk.risk_per_trade_pct / 100 if risk.sizing_method == "stop_risk" else None
    capital_limit = equity * min(risk.max_position_pct, risk.max_exposure_pct) / 100
    if risk.sizing_method == "fixed_notional":
        capital_limit = min(capital_limit, equity * risk.position_pct / 100)
    raw = capital_limit / (entry * (1 + costs.fee))
    if budget is not None:
        raw = min(raw, budget / loss_per_unit)
    step = Decimal(str(execution.quantity_step))
    quantity = float((Decimal(str(raw)) / step).to_integral_value(rounding=ROUND_FLOOR) * step)
    if quantity <= 0 or quantity < execution.min_quantity:
        return "below_min_quantity"
    if quantity * entry < execution.min_notional:
        return "below_min_notional"
    return SizedEntry(
        entry,
        quantity,
        stop,
        target,
        quantity * entry * costs.fee,
        budget,
        quantity * loss_per_unit if loss_per_unit is not None else None,
    )
