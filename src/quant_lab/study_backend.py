"""Study backend v1: reference execution semantics with explicit candle duration.

Copied from reference_v3 without modifying the historical implementation.
"""

from dataclasses import dataclass, replace
from math import isfinite

import pandas as pd

from quant_lab.backtest import BacktestResult, Rejection, Trade, protective_fill
from quant_lab.config import AppConfig, RiskConfig
from quant_lab.execution_config import ExecutionConfig
from quant_lab.risk import CostModel, size_entry
from quant_lab.strategies.base import Signals
from quant_lab.study_data import HOURS, audit


def candle_step(timeframe):
    return pd.Timedelta(minutes=15) if timeframe == "15m" else pd.Timedelta(hours=HOURS[timeframe])


@dataclass(frozen=True)
class Segment:
    symbol: str
    timeframe: str
    start: pd.Timestamp
    end: pd.Timestamp


def validate_segment(candles, history):
    if history.timeframe == "15m":
        from quant_lab.mtf_data import quarter_audit

        report = quarter_audit(candles, history.symbol)
    else:
        report = audit(candles, history.symbol, history.timeframe)
    if report["status"] != "VALID":
        raise ValueError("Execution requires a continuous valid segment")
    step = candle_step(history.timeframe)
    if history.start not in candles.index or candles.index[-1] + step != history.end:
        raise ValueError("Segment boundaries mismatch")


class StudyBackend:
    """Single collateralized position, no pyramiding/reversal at the same open."""

    def run(
        self,
        candles: pd.DataFrame,
        signals: Signals,
        stop_distances: pd.Series,
        history: Segment,
        app: AppConfig,
        risk: RiskConfig,
        execution: ExecutionConfig,
        entry_fractions: pd.Series | None = None,
    ) -> BacktestResult:
        validate_segment(candles, history)
        step = candle_step(history.timeframe)
        arrays = (
            signals.long_entries,
            signals.long_exits,
            signals.short_entries,
            signals.short_exits,
        )
        if any(len(a) != len(candles) or any(type(v) is not bool for v in a) for a in arrays):
            raise ValueError("Signals must have one Python bool per candle")
        if not stop_distances.index.equals(candles.index):
            raise ValueError("Stop distances must align exactly with candle timestamps")
        if risk.sizing_method == "volatility_target" and entry_fractions is None:
            raise ValueError("Volatility sizing requires causal entry fractions")
        if entry_fractions is not None:
            if risk.sizing_method != "volatility_target":
                raise ValueError("Entry fractions require volatility_target sizing")
            if not entry_fractions.index.equals(candles.index):
                raise ValueError("Entry fractions must align exactly with candles")
        costs = CostModel.from_config(app.costs)
        balance = app.starting_capital
        position = None
        side = 0
        entry_time = signal_time = None
        entry_reference = extreme = None
        held_bars = 0
        turnover = 0.0
        trades, rejections = [], []
        equity_times, equity_values = [pd.Timestamp(history.start)], [balance]
        exposure_values = [0.0]
        for i, row in enumerate(candles.itertuples()):
            time = row.Index
            if time < history.start:
                continue
            # Signals formed during warmup cannot open study positions.
            previous = i - 1 if i and candles.index[i - 1] >= history.start else None
            existed = position is not None
            fill = None
            if position is not None:
                fill = protective_fill(row, position, side, opening_only=True)
                exit_signal = previous is not None and (
                    signals.long_exits[previous] if side == 1 else signals.short_exits[previous]
                )
                if fill is None and exit_signal:
                    fill = float(row.open), "signal", "open"
                if (
                    fill is None
                    and risk.max_holding_bars is not None
                    and held_bars >= risk.max_holding_bars
                ):
                    fill = float(row.open), "time_stop", "open"
            if not existed and previous is not None:
                long = execution.direction != "short" and signals.long_entries[previous]
                short = execution.direction != "long" and signals.short_entries[previous]
                if long and short:
                    rejections.append(Rejection(time, "conflicting_entries"))
                elif long or short:
                    side = 1 if long else -1
                    same_exit = (
                        signals.long_exits[previous] if long else signals.short_exits[previous]
                    )
                    if same_exit:
                        rejections.append(Rejection(time, "entry_and_exit_same_signal"))
                    else:
                        entry_risk = risk
                        if entry_fractions is not None:
                            fraction = float(entry_fractions.iloc[previous])
                            if not isfinite(fraction) or not 0 < fraction <= 1:
                                entry_risk = None
                            else:
                                entry_risk = risk.model_copy(
                                    update={
                                        "sizing_method": "fixed_notional",
                                        "position_pct": fraction * 100,
                                    }
                                )
                        sized = (
                            "invalid_entry_fraction"
                            if entry_risk is None
                            else size_entry(
                                balance,
                                float(row.open),
                                float(stop_distances.iloc[previous]),
                                side,
                                entry_risk,
                                execution,
                                costs,
                            )
                        )
                        if isinstance(sized, str):
                            rejections.append(Rejection(time, sized))
                        else:
                            position = sized
                            balance -= sized.entry_fee
                            entry_time = time
                            entry_reference = float(row.open)
                            extreme = None if risk.trailing_basis == "close" else entry_reference
                            held_bars = 0
                            turnover += sized.quantity * sized.price
                            signal_time = candles.index[previous] + step
            if position is not None:
                held_bars += 1
                if fill is None:
                    fill = protective_fill(row, position, side)
                if fill is None and execution.liquidate_at_end and i == len(candles) - 1:
                    fill = float(row.close), "end_of_study", "close"
                if fill is not None:
                    reference, reason, timing = fill
                    price = costs.price(reference, -side)
                    exit_fee = position.quantity * price * costs.fee
                    gross = side * position.quantity * (price - position.price)
                    balance += gross - exit_fee
                    turnover += position.quantity * price
                    exit_time = (
                        time if timing == "open" else time + step if timing == "close" else None
                    )
                    trades.append(
                        Trade(
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
                            gross - position.entry_fee - exit_fee,
                            reason,
                            position.risk_budget,
                            position.expected_stop_loss,
                            entry_reference,
                            reference,
                            position.quantity
                            * (entry_reference + reference)
                            * app.costs.slippage_pct
                            / 100,
                            position.quantity
                            * (entry_reference + reference)
                            * app.costs.spread_pct
                            / 200,
                            held_bars - (1 if timing == "open" else 0),
                        )
                    )
                    position = None
                elif risk.trailing_atr_multiplier is not None:
                    # Only surviving positions observe this bar's complete high/low.
                    # The resulting level becomes active on the NEXT iteration.
                    observed = (
                        float(row.close)
                        if risk.trailing_basis == "close"
                        else float(row.high if side == 1 else row.low)
                    )
                    extreme = (
                        observed
                        if extreme is None
                        else (max(extreme, observed) if side == 1 else min(extreme, observed))
                    )
                    distance = float(stop_distances.iloc[i])
                    if isfinite(distance) and distance > 0:
                        trailing = extreme - side * (
                            distance / risk.atr_multiplier * risk.trailing_atr_multiplier
                        )
                        level = (
                            max(position.stop, trailing)
                            if side == 1
                            else min(position.stop, trailing)
                        )
                        position = replace(position, stop=level)
            equity = (
                balance
                if position is None
                else (balance + side * position.quantity * (float(row.close) - position.price))
            )
            equity_times.append(time + step)
            equity_values.append(equity)
            exposure_values.append(
                position.quantity * float(row.close) / equity
                if position is not None and equity > 0
                else 0.0
            )
        open_position = (
            None
            if position is None
            else {
                "side": "long" if side == 1 else "short",
                "entry_price": position.price,
                "quantity": position.quantity,
                "stop": position.stop,
                "target": position.target,
                "entry_time": entry_time,
                "entry_fee": position.entry_fee,
            }
        )
        return BacktestResult(
            tuple(trades),
            pd.Series(equity_values, index=pd.DatetimeIndex(equity_times), name="equity"),
            tuple(rejections),
            open_position,
            execution.direction,
            execution.market_mode,
            pd.Series(exposure_values, index=pd.DatetimeIndex(equity_times), name="exposure"),
            turnover,
        )
