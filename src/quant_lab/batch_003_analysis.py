"""Frozen descriptive analysis for reused-history Batch 003; never feeds signals."""

import hashlib
import itertools

import numpy as np
import pandas as pd

from quant_lab.features import atr, ema

LABEL = "REUSED_HISTORY_DIAGNOSTIC"


def select_train(rows, baseline):
    if not rows or any(r["partition"] != "train" or r["costs"] != "base" for r in rows):
        raise ValueError("Selection accepts train/base only")
    eligible = [
        r
        for r in rows
        if r["return_pct"] > 0
        and (r["sharpe"] or 0) > 0
        and (r["profit_factor"] or 0) > 1
        and r["closed_trades"] >= 40
        and r["max_drawdown_pct"] < 20
    ]
    if not eligible:
        return {
            "candidate": baseline,
            "train_eligible": False,
            "diagnostic": "INSUFFICIENT_DATA"
            if all(r["closed_trades"] < 40 for r in rows)
            else "REJECTED_TRAIN",
            "eligible_variants": [],
        }
    top = max(r["sharpe"] for r in eligible)
    near = [r for r in eligible if top - r["sharpe"] <= 0.01]
    chosen = min(near, key=lambda r: (r["max_drawdown_pct"], -r["profit_factor"], r["candidate"]))
    return {
        "candidate": chosen["candidate"],
        "train_eligible": True,
        "diagnostic": "TRAIN_ELIGIBLE",
        "eligible_variants": [r["candidate"] for r in eligible],
    }


def streak(values, winning=False):
    return max(
        (
            len(list(g))
            for key, g in itertools.groupby(values, lambda x: x > 0 if winning else x < 0)
            if key
        ),
        default=0,
    )


def extended_metrics(result):
    pnl = [t.net_pnl for t in result.trades]
    gross = sum(t.quantity * (t.exit_reference - t.entry_reference) for t in result.trades)
    total = sum(t.entry_fee + t.exit_fee + t.slippage_cost + t.spread_cost for t in result.trades)
    wins, losses = [p for p in pnl if p > 0], [p for p in pnl if p < 0]
    return {
        "gross_pnl": gross,
        "gross_return_pct": gross / result.equity.iloc[0] * 100,
        "total_costs": total,
        "cost_per_trade": total / len(pnl) if pnl else None,
        "payoff_ratio": float(np.mean(wins) / -np.mean(losses)) if wins and losses else None,
        "best_trade": max(pnl) if pnl else None,
        "worst_trade": min(pnl) if pnl else None,
        "max_winning_streak": streak(pnl, True),
        "max_losing_streak": streak(pnl),
        "gross_convention": "Reference-price PnL on actual fixed trades; not a zero-cost rerun",
    }


def regimes(frame):
    fast, slow = ema(frame.close, 50), ema(frame.close, 200)
    trend = pd.Series("UNKNOWN", index=frame.index)
    trend.loc[fast > slow] = "BULL_TREND"
    trend.loc[fast < slow] = "BEAR_TREND"
    trend.loc[(fast / slow - 1).abs() <= 0.0025] = "SIDEWAYS"
    ratio = atr(frame, 14) / frame.close
    past = ratio.shift(1).rolling(720)
    low, high = past.quantile(0.3), past.quantile(0.7)
    vol = pd.Series("UNKNOWN", index=frame.index)
    vol.loc[high.notna()] = "NORMAL_VOLATILITY"
    vol.loc[ratio > high] = "HIGH_VOLATILITY"
    vol.loc[ratio < low] = "LOW_VOLATILITY"
    return pd.DataFrame({"trend": trend, "volatility": vol})


def regime_analysis(frame, result):
    labels = regimes(frame)
    # Equity increments end one hour after bar open. Use previous bar's closed information.
    known = labels.copy()
    known.index = known.index + pd.Timedelta(hours=2)
    known = known.reindex(result.equity.index[1:])
    increments = result.equity.diff().iloc[1:]
    report = {}
    for axis in labels:
        by_trade = {}
        for t in result.trades:
            label = labels.loc[t.signal_close - pd.Timedelta(hours=1), axis]
            by_trade.setdefault(label, []).append(t.net_pnl)
        rows = {}
        for label in sorted(set(known[axis].dropna()) | set(by_trade)):
            mask = known[axis] == label
            pnls = by_trade.get(label, [])
            gains, losses = sum(p for p in pnls if p > 0), -sum(p for p in pnls if p < 0)
            rows[label] = {
                "trades": len(pnls),
                "trade_net_pnl": sum(pnls),
                "trade_return_contribution_pct": sum(pnls) / result.equity.iloc[0] * 100,
                "bar_return_contribution_pct": float(
                    increments.loc[mask].sum() / result.equity.iloc[0] * 100
                ),
                "win_rate_pct": sum(p > 0 for p in pnls) / len(pnls) * 100 if pnls else None,
                "profit_factor": gains / losses if losses else None,
                "expectancy": sum(pnls) / len(pnls) if pnls else None,
                "average_close_exposure_pct": float(result.exposure.iloc[1:].loc[mask].mean() * 100)
                if mask.any()
                else None,
                "bars": int(mask.sum()),
            }
        report[axis] = rows
    return {
        "interpretation": LABEL,
        "axes": report,
        "convention": (
            "Two overlapping axes; never sum across axes. Trade attribution at "
            "signal close; bar PnL at preceding close. Return contributions use "
            "starting equity. Exposure is mean close exposure conditional on "
            "regime."
        ),
    }


def monte_carlo(pnls, key, capital=10000.0, simulations=10000):
    if len(pnls) < 30:
        return {"status": "INSUFFICIENT_DATA", "trades": len(pnls), "minimum": 30}, None
    seed = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")
    rng = np.random.default_rng(seed)
    values = np.asarray(pnls, dtype=float)
    samples = np.empty((simulations, 3))
    for offset in range(0, simulations, 250):
        size = min(250, simulations - offset)
        shuffled = np.array([rng.permutation(values) for _ in range(size)])
        equity = np.column_stack([np.full(size, capital), capital + shuffled.cumsum(axis=1)])
        peaks = np.maximum.accumulate(equity, axis=1)
        dd = ((peaks - equity) / peaks).max(axis=1) * 100
        current, longest = np.zeros(size, dtype=int), np.zeros(size, dtype=int)
        for col in shuffled.T:
            current = np.where(col < 0, current + 1, 0)
            longest = np.maximum(longest, current)
        samples[offset : offset + size] = np.column_stack(
            [np.full(size, values.sum() / capital * 100), dd, longest]
        )
    return {
        "status": "completed",
        "seed": seed,
        "simulations": simulations,
        "trades": len(values),
        "method": (
            "Permutation of fixed realized cash PnLs; no re-sizing or "
            "re-execution; final return invariant. Closed-trade drawdown, not "
            "intrabar drawdown or forecast."
        ),
        "percentiles": {
            name: dict(
                zip(
                    ("5", "25", "50", "75", "95"),
                    np.percentile(samples[:, i], [5, 25, 50, 75, 95]).tolist(),
                    strict=True,
                )
            )
            for i, name in enumerate(("return_pct", "drawdown_pct", "losing_streak"))
        },
    }, samples
