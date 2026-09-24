"""Independent accounts with no positions/features across quarantined data gaps."""

import numpy as np
import pandas as pd

from quant_lab.backtest import BacktestResult
from quant_lab.config import AppConfig
from quant_lab.features import atr
from quant_lab.risk import CostModel
from quant_lab.study_backend import Segment, StudyBackend
from quant_lab.study_data import HOURS, hours_to_bars
from quant_lab.study_features import prepare, regimes, signals, volatility


def continuous_blocks(frame, timeframe):
    step = pd.Timedelta(hours=HOURS[timeframe])
    groups = (frame.index.to_series().diff() != step).cumsum()
    return [group for _, group in frame.groupby(groups)]


def prepare_blocks(strategy, frame, timeframe):
    return [
        (part, prepare(strategy, part, timeframe), regimes(part, timeframe))
        for part in continuous_blocks(frame, timeframe)
    ]


def execute(strategy, blocks, asset, timeframe, start, end, costs, execution):
    risk = strategy.config.risk
    if risk.max_holding_bars is not None:
        risk = risk.model_copy(
            update={"max_holding_bars": hours_to_bars(risk.max_holding_bars, timeframe)}
        )
    balance = 10000.0
    trades, rejects, equities, exposures, labels = [], [], [], [], []
    turnover = 0.0
    step = pd.Timedelta(hours=HOURS[timeframe])
    for source, prepared, label in blocks:
        left, right = max(start, source.index[0]), min(end, source.index[-1] + step)
        if right <= left:
            continue
        # Preceding history is causal warmup only. Every partition starts flat.
        frame = source.loc[source.index < right]
        features = prepared.loc[frame.index]
        distances = atr(frame, risk.atr_period) * risk.atr_multiplier
        app = AppConfig(starting_capital=balance, costs=costs)
        fractions = None
        if risk.sizing_method == "volatility_target":
            vol = volatility(
                frame.close, hours_to_bars(risk.volatility_period, timeframe), timeframe
            )
            fractions = (
                (risk.target_volatility_pct / 100 / vol)
                .clip(
                    risk.min_position_pct / 100,
                    min(risk.max_position_pct, risk.max_exposure_pct) / 100,
                )
                .where(np.isfinite(vol) & (vol > 0))
            )
        if risk.stop_method == "structure":
            # Execution adaptation uses ONLY the next opening quote, never next high/low/close.
            opening = frame.open.shift(-1)
            entry = CostModel.from_config(costs).price(opening, 1)
            distance = entry - features.stop_anchor
            valid = (
                (features.stop_anchor > 0)
                & (opening > features.stop_anchor)
                & (distance > 0)
                & (distance <= distances)
            )
            distances = distance.where(valid)
        result = StudyBackend().run(
            frame,
            signals(strategy, features),
            distances,
            Segment(asset, timeframe, left, right),
            app,
            risk,
            execution,
            fractions,
        )
        if result.open_position is not None:
            raise AssertionError("Position crossed segment boundary")
        entry_equity = balance
        for trade in result.trades:
            entry_cost = trade.quantity * trade.entry_price + trade.entry_fee
            cap = min(risk.max_position_pct, risk.max_exposure_pct) / 100
            if entry_cost > entry_equity * cap + 1e-7:
                raise AssertionError("Exposure cap exceeded at entry")
            entry_equity += trade.net_pnl
            if not (left < trade.entry_time < right and trade.signal_close == trade.entry_time):
                raise AssertionError("Noncausal or out-of-window fill")
            if (
                trade.expected_stop_loss is not None
                and trade.expected_stop_loss > trade.risk_budget + 1e-7
            ):
                raise AssertionError("Risk budget exceeded at entry")
        if not np.isclose(result.equity.iloc[-1] - balance, sum(t.net_pnl for t in result.trades)):
            raise AssertionError("Cash reconciliation failed")
        balance = float(result.equity.iloc[-1])
        trades.extend(result.trades)
        rejects.extend(result.rejections)
        turnover += result.turnover
        equities.append(result.equity)
        exposures.append(result.exposure)
        labels.append(label.loc[(label.index >= left) & (label.index < right)])
    grid = pd.date_range(start, end, freq=timeframe)
    if equities:
        eq = pd.concat(equities)
        exp = pd.concat(exposures)
        eq = eq[~eq.index.duplicated(keep="last")]
        exp = exp[~exp.index.duplicated(keep="last")]
        eq.loc[start] = 10000.0
        # Only ACCOUNT cash is carried flat across exclusions; never manufacture OHLCV.
        eq = eq.sort_index().reindex(grid).ffill()
        exp = exp.reindex(grid).fillna(0)
    else:
        eq, exp = pd.Series(10000.0, index=grid), pd.Series(0.0, index=grid)
    combined = BacktestResult(
        tuple(trades), eq, tuple(rejects), None, "long", "spot", exp, turnover
    )
    return combined, pd.concat(labels) if labels else pd.DataFrame()


def attribution(result, labels, timeframe):
    step = pd.Timedelta(hours=HOURS[timeframe])
    report = {}
    if labels.empty:
        return report
    known = labels.copy()
    known.index += 2 * step
    known = known.reindex(result.equity.index[1:]).fillna("NO_PRIOR_DATA")
    for axis in labels:
        groups = {}
        for trade in result.trades:
            key = labels.loc[trade.signal_close - step, axis]
            groups.setdefault(key, []).append(trade.net_pnl)
        values = {}
        for label in sorted(set(known[axis]) | set(groups)):
            pnls = groups.get(label, [])
            loss = -sum(p for p in pnls if p < 0)
            mask = known[axis] == label
            values[label] = {
                "trades": len(pnls),
                "trade_pnl": sum(pnls),
                "profit_factor": sum(p for p in pnls if p > 0) / loss if loss else None,
                "bar_pnl": float(result.equity.diff().iloc[1:].loc[mask].sum()),
                "bars": int(mask.sum()),
            }
        report[axis] = values
    return report


def annual_windows(start, end):
    for year in range(start.year, end.year + 1):
        a, b = (
            max(start, pd.Timestamp(f"{year}-01-01", tz="UTC")),
            min(end, pd.Timestamp(f"{year + 1}-01-01", tz="UTC")),
        )
        if a < b:
            yield f"year_{year}", a, b
