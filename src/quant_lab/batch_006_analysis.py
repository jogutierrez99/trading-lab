"""Directional excursions, PnL decomposition and causal regime attribution."""

from dataclasses import replace

import numpy as np
import pandas as pd

from quant_lab.batch_003_analysis import streak
from quant_lab.metrics import summarize
from quant_lab.study_data import HOURS
from quant_lab.study_excursions import entry_diagnostics


def trade_statistics(trades):
    pnl = [t.net_pnl for t in trades]
    gains = sum(p for p in pnl if p > 0)
    losses = -sum(p for p in pnl if p < 0)
    return {
        "trades": len(pnl),
        "pnl": sum(pnl),
        "profit_factor": gains / losses if losses else None,
        "win_rate_pct": 100 * sum(p > 0 for p in pnl) / len(pnl) if pnl else None,
        "expectancy": sum(pnl) / len(pnl) if pnl else None,
        "average_trade": sum(pnl) / len(pnl) if pnl else None,
        "funding_pnl": sum(t.funding_pnl for t in trades),
    }


def signal_follow_through(blocks, start, end, timeframe):
    """All close-entry signals, including those ignored while already in a position."""
    horizons = {f"{n}_bars": n * HOURS[timeframe] for n in (1, 3, 6, 12, 24)}
    horizons.update({f"{h}_hours": h for h in (6, 12, 24, 48, 72) if h % HOURS[timeframe] == 0})
    records = {"long": [], "short": []}
    for frame, _mark, _funding, decisions, _labels in blocks:
        left, right = max(start, frame.index[0]), min(end, frame.index[-1] + pd.Timedelta(hours=1))
        eligible = decisions.loc[(decisions.index > left) & (decisions.index < right)]
        for side, column, sign in (("long", "le", 1), ("short", "se", -1)):
            for time in eligible.index[eligible[column]]:
                reference = frame.loc[time, "open"]
                returns = {}
                for label, hours in horizons.items():
                    target = time + pd.Timedelta(hours=hours - 1)
                    returns[label] = (
                        float(sign * (frame.loc[target, "close"] / reference - 1) * 100)
                        if target in frame.index and target + pd.Timedelta(hours=1) <= right
                        else None
                    )
                records[side].append({"signal_close": str(time), "returns_pct": returns})
    summary = {}
    for side, items in records.items():
        summary[side] = {}
        for label in horizons:
            values = [r["returns_pct"][label] for r in items if r["returns_pct"][label] is not None]
            summary[side][label] = {
                "n": len(values),
                "censored": len(items) - len(values),
                "mean": float(np.mean(values)) if values else None,
                "median": float(np.median(values)) if values else None,
            }
    return {
        "signals": records,
        "summary": summary,
        "convention": "All eligible signals, next-open reference, raw directional returns; "
        "includes ignored entries, overlapping horizons are not independent.",
    }


def excursions(frame, result, timeframe):
    """Map short price paths by linear reflection; percent excursions stay entry-relative.

    Hourly execution data determines excursion bounds; reporting horizons follow strategy TF.
    """
    quality = {"long": [], "short": []}
    edges = {"long": [], "short": []}
    horizons = {f"{n}_bars": n * HOURS[timeframe] for n in (1, 3, 6, 12, 24)}
    horizons.update({f"{h}_hours": h for h in (6, 12, 24, 48, 72) if h % HOURS[timeframe] == 0})
    for i, t in enumerate(result.trades):
        side = 1 if t.side == "long" else -1
        # Restrict each excursion calculation to the position's known execution bars.
        subset = frame.loc[t.entry_time : t.exit_bar_open].copy()
        observed = t
        if side == -1:
            origin = 2 * t.entry_reference
            old_high = subset.high.copy()
            subset["high"] = origin - subset.low
            subset["low"] = origin - old_high
            subset["open"] = origin - subset.open
            subset["close"] = origin - subset.close
            observed = replace(t, side="long", exit_reference=origin - t.exit_reference)
        q, _, _ = entry_diagnostics(subset, replace(result, trades=(observed,)), "1h")
        item = q["trades"][0] | {"trade_index": i, "side": t.side}
        quality[t.side].append(item)
        returns = {}
        for label, hours in horizons.items():
            target = t.entry_time + pd.Timedelta(hours=hours - 1)
            history = frame.loc[t.entry_time : target]
            returns[label] = (
                float(side * (frame.loc[target, "close"] / t.entry_reference - 1) * 100)
                if target in frame.index
                and target + pd.Timedelta(hours=1) <= result.equity.index[-1]
                and len(history) == hours
                else None
            )
        edges[t.side].append(
            {"trade_index": i, "entry_time": str(t.entry_time), "returns_pct": returns}
        )
    summary = {}
    follow = {}
    for side in quality:
        records = quality[side]
        fields = (
            "mfe_pct",
            "mae_pct",
            "time_to_mfe_hours_lower",
            "time_to_mfe_hours_upper",
            "time_to_mae_hours_lower",
            "time_to_mae_hours_upper",
        )
        stats = {
            f"{key}_{agg}": float(getattr(np, agg)([r[key] for r in records])) if records else None
            for key in fields
            for agg in ("mean", "median")
        }
        stats["mfe_mae_ratio"] = (
            stats["mfe_pct_mean"] / stats["mae_pct_mean"]
            if stats["mae_pct_mean"] and stats["mae_pct_mean"] > 0
            else None
        )
        summary[side] = stats
        follow[side] = {}
        for label in horizons:
            values = [
                r["returns_pct"][label] for r in edges[side] if r["returns_pct"][label] is not None
            ]
            follow[side][label] = {
                "n": len(values),
                "censored": len(edges[side]) - len(values),
                "mean": float(np.mean(values)) if values else None,
                "median": float(np.median(values)) if values else None,
            }
    return {
        "trades": quality,
        "summary": summary,
        "convention": (
            "Directional entry-reference price excursions, hourly intrabar "
            "lower/upper bounds. Funding/fees excluded. Short favorable=down, "
            "adverse=up."
        ),
    }, {
        "trades": edges,
        "summary": follow,
        "convention": (
            "Directional raw-price follow-through after executed entries; may "
            "outlive position, never crosses data gap/window. Not all unfilled"
            " signals."
        ),
    }


def metrics(result, sides, quality, include_funding=True):
    values = summarize(result)
    trades = result.trades
    gross = sum(
        (1 if t.side == "long" else -1) * t.quantity * (t.exit_reference - t.entry_reference)
        for t in trades
    )
    fees = sum(t.entry_fee + t.exit_fee for t in trades)
    slip = sum(t.slippage_cost for t in trades)
    spread = sum(t.spread_cost for t in trades)
    funding = sum(t.funding_pnl for t in trades)
    liquidation = sum(t.liquidation_fee for t in trades)
    bankruptcy = sum(t.bankruptcy_adjustment for t in trades)
    if not np.isclose(
        gross - fees - slip - spread + funding - liquidation + bankruptcy,
        values["realized_net_pnl"],
        atol=1e-6,
    ):
        raise AssertionError("Directional gross/net/funding reconciliation")
    pnl = [t.net_pnl for t in trades]
    win = [p for p in pnl if p > 0]
    loss = [p for p in pnl if p < 0]
    values.update(
        {
            "gross_pnl": gross,
            "gross_return_pct": gross / result.equity.iloc[0] * 100,
            "fees": fees,
            "slippage_cost": slip,
            "spread_cost": spread,
            "funding_pnl": funding,
            "funding_cost": -funding,
            "funding_note": (
                "Historical settlement rates; mark-open notional"
                if include_funding
                else "Disabled in ZERO/cash, not missing source data"
            ),
            "liquidation_fees": liquidation,
            "bankruptcy_adjustment": bankruptcy,
            "liquidations": sum(t.reason.startswith("liquidation") for t in trades),
            "total_execution_costs": fees + slip + spread + liquidation,
            "payoff_ratio": float(np.mean(win) / -np.mean(loss)) if win and loss else None,
            "best_trade": max(pnl) if pnl else None,
            "worst_trade": min(pnl) if pnl else None,
            "longest_win_streak": streak(pnl, True),
            "longest_loss_streak": streak(pnl),
            "average_holding_hours": values["average_holding_bars"],
        }
    )
    for side, sign in (("long", 1), ("short", -1)):
        selected = [t for t in trades if t.side == side]
        values.update({f"{side}_{k}": v for k, v in trade_statistics(selected).items()})
        values[f"{side}_contribution_pct"] = (
            sum(t.net_pnl for t in selected) / result.equity.iloc[0] * 100
        )
        values[f"{side}_exposure_pct"] = float(
            result.exposure.iloc[1:].where(sides.iloc[1:] == sign, 0).mean() * 100
        )
        values[f"{side}_mfe_mae"] = quality["summary"][side]["mfe_mae_ratio"]
    positive_gross = sum(
        max(
            0, (1 if t.side == "long" else -1) * t.quantity * (t.exit_reference - t.entry_reference)
        )
        for t in trades
    )
    values["funding_as_pct_gross_profit"] = (
        funding / positive_gross * 100 if positive_gross > 0 else None
    )
    values["gross_profit_denominator"] = positive_gross
    return values


def regimes_by_side(result, labels):
    report = {}
    for axis in labels:
        report[axis] = {}
        for t in result.trades:
            label = labels.loc[t.signal_close, axis]
            report[axis].setdefault(label, {"long": [], "short": []})[t.side].append(t)
        report[axis] = {
            label: {side: trade_statistics(trades) for side, trades in pairs.items()}
            for label, pairs in report[axis].items()
        }
    return report
