"""Absolute protective levels at next open, reusing the existing cost-aware sizing."""

from dataclasses import replace
from math import isfinite

from quant_lab.risk import size_entry


def size_with_levels(equity, opening, levels, side, risk, execution, costs):
    prefix = "long" if side == 1 else "short"
    stop, target = float(levels[prefix + "_stop"]), float(levels[prefix + "_target"])
    entry = costs.price(opening, side)
    if not all(isfinite(v) and v > 0 for v in (stop, target, entry)):
        return "invalid_absolute_levels"
    if side * (opening - stop) <= 0 or side * (target - opening) <= 0:
        return "open_outside_frozen_levels"
    distance, reward = side * (entry - stop), side * (target - entry)
    if distance <= 0 or reward <= 0:
        return "cost_adjusted_entry_outside_levels"
    sized = size_entry(
        equity,
        opening,
        distance,
        side,
        risk.model_copy(update={"risk_reward": reward / distance}),
        execution,
        costs,
    )
    return sized if isinstance(sized, str) else replace(sized, stop=stop, target=target)
