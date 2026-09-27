"USD-M isolated1x research execution; actual funding and hourly mark-price checks."

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quant_lab.backtest import BacktestResult, Rejection, Trade, protective_fill
from quant_lab.risk import CostModel, size_entry


@dataclass(frozen=True)
class FuturesAssumptions:
    quantity_step: float = 0.001
    min_quantity: float = 0.001
    min_notional: float = 5.0
    maintenance_margin_pct: float = 0.5
    liquidation_fee_pct: float = 0.5
    leverage: float = 1.0
    market_mode: str = "perpetual"
    note: str = (
        "Fixed lot filters, maintenance0.5% and liquidation fee0.5% are "
        "research assumptions; historical tier schedules unavailable. "
        "Isolated margin, no auto-add; bankruptcy loss capped at allocated"
        " margin, historical insurance/ADL not replicated."
    )


@dataclass(frozen=True)
class PerpetualTrade(Trade):
    funding_pnl: float
    funding_events: int
    initial_margin: float
    maintenance_margin_at_exit: float
    liquidation_fee: float
    margin_model: str
    bankruptcy_adjustment: float


def funding_pnl(side, quantity, mark_price, rate):
    return -side * quantity * mark_price * rate


def margin_breached(side, quantity, entry, isolated_margin, mark, maintenance_pct):
    return (
        isolated_margin + side * quantity * (mark - entry)
        <= quantity * mark * maintenance_pct / 100
    )


def run_perpetual(
    candles,
    mark,
    funding,
    decisions,
    start,
    end,
    costs,
    risk,
    assumptions=None,
    capital=10000.0,
    include_funding=True,
    direction="combined",
    execution_policy=None,
):
    """decisions index = closed strategy-candle availability, not its opening time.

    Funding applies to positions held immediately before settlement; then open liquidation,
    protective gaps, close-derived exits, time stop, new entry. Intrabar liquidation precedes
    stop if ordering cannot be identified. New entries never receive same-boundary funding.
    """
    assumptions = assumptions or FuturesAssumptions()
    if assumptions.leverage != 1 or direction not in {"long", "short", "combined"}:
        raise ValueError("Only independent1x modes supported")
    if not candles.index.equals(mark.index) or not candles.index.is_unique:
        raise ValueError("Execution and mark bars must align exactly")
    if (
        len(candles) > 1
        and not (candles.index.to_series().diff().iloc[1:] == pd.Timedelta(hours=1)).all()
    ):
        raise ValueError("Execution cannot cross gaps")
    if not decisions.index.is_unique or not funding.index.is_unique:
        raise ValueError("Duplicate funding/decision time")
    cost = CostModel.from_config(costs)
    balance = capital
    position = None
    side = 0
    entry_time = signal_time = None
    reference = initial_margin = isolated_margin = fund_pnl = 0.0
    fund_count = 0
    trades, rejections, fund_events = [], [], []
    times, values, exposure, directions = [start], [capital], [0.0], [0]
    turnover = 0.0
    decision_map = decisions.to_dict("index")
    funding_map = (
        {
            hour: (t, rate)
            for hour, t, rate in zip(
                funding.index.floor("h"), funding.index, funding.rate, strict=True
            )
        }
        if include_funding
        else {}
    )
    step = pd.Timedelta(hours=1)
    for i, (row, m) in enumerate(zip(candles.itertuples(), mark.itertuples(), strict=True)):
        time = row.Index
        if time < start:
            continue
        existed = position is not None
        fill = None
        liquidation_fee = 0.0
        signal = decision_map.get(time)
        if execution_policy is not None:
            signal = execution_policy.decision(time, float(row.open), existed)
        # A warmup-close signal cannot open a position exactly at partition start.
        if position is not None:
            if time in funding_map and funding_map[time][0] == time:
                amount = funding_pnl(side, position.quantity, float(m.open), funding_map[time][1])
                balance += amount
                isolated_margin += amount
                fund_pnl += amount
                fund_count += 1
                fund_events.append(
                    {
                        "time": time,
                        "side": side,
                        "rate": funding_map[time][1],
                        "mark": float(m.open),
                        "quantity": position.quantity,
                        "pnl": amount,
                    }
                )
            if margin_breached(
                side,
                position.quantity,
                position.price,
                isolated_margin,
                float(m.open),
                assumptions.maintenance_margin_pct,
            ):
                fill = float(row.open), "liquidation_gap", "open"
            if fill is None:
                fill = protective_fill(row, position, side, opening_only=True)
            if fill is None and signal is not None and signal["lx" if side == 1 else "sx"]:
                fill = float(row.open), "signal", "open"
            if (
                fill is None
                and risk.max_holding_bars is not None
                and time - entry_time >= pd.Timedelta(hours=risk.max_holding_bars)
            ):
                fill = float(row.open), "time_stop", "open"
        if not existed and signal is not None and time > start:
            long = bool(signal["le"]) and direction != "short"
            short = bool(signal["se"]) and direction != "long"
            if long and short:
                rejections.append(Rejection(time, "conflicting_entries"))
            elif long or short:
                side = 1 if long else -1
                if signal["lx" if side == 1 else "sx"]:
                    rejections.append(Rejection(time, "entry_and_exit_same_signal"))
                else:
                    sized = size_entry(
                        balance,
                        float(row.open),
                        float(signal["distance"]),
                        side,
                        risk,
                        assumptions,
                        cost,
                    )
                    if isinstance(sized, str):
                        rejections.append(Rejection(time, sized))
                    else:
                        position = sized
                        balance -= sized.entry_fee
                        entry_time = signal_time = time
                        reference = float(row.open)
                        initial_margin = isolated_margin = sized.quantity * sized.price
                        fund_pnl = 0.0
                        fund_count = 0
                        turnover += sized.quantity * sized.price
                        if execution_policy is not None:
                            execution_policy.on_entry(time, sized.price)
        if (
            position is not None
            and fill is None
            and time in funding_map
            and funding_map[time][0] > time
        ):
            actual_time, rate = funding_map[time]
            amount = funding_pnl(side, position.quantity, float(m.open), rate)
            balance += amount
            isolated_margin += amount
            fund_pnl += amount
            fund_count += 1
            fund_events.append(
                {
                    "time": actual_time,
                    "side": side,
                    "rate": rate,
                    "mark": float(m.open),
                    "quantity": position.quantity,
                    "pnl": amount,
                }
            )
        if position is not None:
            adverse_mark = float(m.low if side == 1 else m.high)
            if fill is None and margin_breached(
                side,
                position.quantity,
                position.price,
                isolated_margin,
                adverse_mark,
                assumptions.maintenance_margin_pct,
            ):
                fill = float(row.low if side == 1 else row.high), "liquidation_intrabar", "intrabar"
            if fill is None:
                fill = protective_fill(row, position, side)
            if fill is None and i == len(candles) - 1:
                fill = float(row.close), "end_of_segment", "close"
            if fill is not None:
                exit_reference, reason, timing = fill
                price = cost.price(exit_reference, -side)
                exit_fee = position.quantity * price * cost.fee
                if reason.startswith("liquidation"):
                    liquidation_fee = (
                        position.quantity * price * assumptions.liquidation_fee_pct / 100
                    )
                price_pnl = side * position.quantity * (price - position.price)
                bankruptcy_adjustment = (
                    max(0.0, -(isolated_margin + price_pnl - exit_fee - liquidation_fee))
                    if reason.startswith("liquidation")
                    else 0.0
                )
                balance += price_pnl - exit_fee - liquidation_fee + bankruptcy_adjustment
                net = (
                    price_pnl
                    - position.entry_fee
                    - exit_fee
                    + fund_pnl
                    - liquidation_fee
                    + bankruptcy_adjustment
                )
                exit_time = time if timing == "open" else time + step if timing == "close" else None
                bars = int((time - entry_time) / pd.Timedelta(hours=1)) + (timing != "open")
                trades.append(
                    PerpetualTrade(
                        "long" if side == 1 else "short",
                        signal_time,
                        entry_time,
                        time,
                        exit_time,
                        timing,
                        position.price,
                        price,
                        position.quantity,
                        position.stop,
                        position.target,
                        position.entry_fee,
                        exit_fee,
                        net,
                        reason,
                        position.risk_budget,
                        position.expected_stop_loss,
                        reference,
                        exit_reference,
                        position.quantity * (reference + exit_reference) * costs.slippage_pct / 100,
                        position.quantity * (reference + exit_reference) * costs.spread_pct / 200,
                        int(bars),
                        fund_pnl,
                        fund_count,
                        initial_margin,
                        position.quantity
                        * float(m.open if timing == "open" else adverse_mark)
                        * assumptions.maintenance_margin_pct
                        / 100,
                        liquidation_fee,
                        "ISOLATED_1X_RESEARCH_ASSUMPTION",
                        bankruptcy_adjustment,
                    )
                )
                turnover += position.quantity * price
                position = None
                if execution_policy is not None:
                    execution_policy.on_exit(time if timing == "open" else time + step)
        equity = (
            balance
            if position is None
            else balance + side * position.quantity * (float(m.close) - position.price)
        )
        times.append(time + step)
        values.append(equity)
        exposure.append(
            position.quantity * float(m.close) / equity
            if position is not None and equity > 0
            else 0.0
        )
        directions.append(side if position is not None else 0)
    if position is not None or not np.isclose(
        values[-1] - capital, sum(t.net_pnl for t in trades), atol=1e-7
    ):
        raise AssertionError("Perpetual cash reconciliation failed")
    result = BacktestResult(
        tuple(trades),
        pd.Series(values, index=pd.DatetimeIndex(times)),
        tuple(rejections),
        None,
        direction,
        "perpetual",
        pd.Series(exposure, index=pd.DatetimeIndex(times)),
        turnover,
    )
    return result, pd.Series(directions, index=pd.DatetimeIndex(times)), fund_events
