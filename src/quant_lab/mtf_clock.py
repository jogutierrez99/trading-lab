"""Unit conversion adapter: reuse the frozen hourly engine without changing prices."""

from dataclasses import replace

import pandas as pd

from quant_lab.perpetual_execution import run_perpetual

ANCHOR = pd.Timestamp("2020-01-01", tz="UTC")


def stretch(value, factor: float):
    if value is None:
        return None
    delta = value - ANCHOR
    return ANCHOR + (delta // int(1 / factor) if factor < 1 else delta * int(factor))


def clock_frame(frame: pd.DataFrame, factor: float) -> pd.DataFrame:
    result = frame.copy()
    result.index = stretch(result.index, factor)
    return result


def execute(
    candles,
    mark,
    funding,
    decisions,
    start,
    end,
    costs,
    risk,
    capital=10000.0,
    include_funding=True,
    direction="long",
    timeframe="1h",
    execution_policy=None,
):
    factor = 4 if timeframe == "15m" else 1
    engine_risk = risk.model_copy(update={"max_holding_bars": risk.max_holding_bars * factor})
    result, sides, events = run_perpetual(
        clock_frame(candles, factor),
        clock_frame(mark, factor),
        clock_frame(funding, factor),
        clock_frame(decisions, factor),
        stretch(start, factor),
        stretch(end, factor),
        costs,
        engine_risk,
        capital=capital,
        include_funding=include_funding,
        direction=direction,
        execution_policy=ClockPolicy(execution_policy, factor) if execution_policy else None,
    )
    trades = tuple(
        replace(
            t,
            **{
                field: stretch(getattr(t, field), 1 / factor)
                for field in ("signal_close", "entry_time", "exit_bar_open", "exit_time")
            },
        )
        for t in result.trades
    )
    rejections = tuple(replace(r, time=stretch(r.time, 1 / factor)) for r in result.rejections)
    equity = result.equity.copy()
    equity.index = stretch(equity.index, 1 / factor)
    exposure = result.exposure.copy()
    exposure.index = stretch(exposure.index, 1 / factor)
    sides = sides.copy()
    sides.index = stretch(sides.index, 1 / factor)
    events = [e | {"time": stretch(e["time"], 1 / factor)} for e in events]
    return (
        replace(result, trades=trades, rejections=rejections, equity=equity, exposure=exposure),
        sides,
        events,
    )


class ClockPolicy:
    """Expose only real UTC instants to an optional execution policy."""

    def __init__(self, policy, factor):
        self.policy = policy
        self.factor = factor

    def decision(self, time, opening_price, has_position):
        return self.policy.decision(stretch(time, 1 / self.factor), opening_price, has_position)

    def on_entry(self, time, price):
        self.policy.on_entry(stretch(time, 1 / self.factor), price)

    def on_exit(self, time):
        self.policy.on_exit(stretch(time, 1 / self.factor))
