"""Predefined train selection and descriptive analyses for Batch 004."""

import hashlib

import numpy as np
import pandas as pd

from quant_lab.batch_003_analysis import regime_analysis as previous_regime_analysis
from quant_lab.batch_003_analysis import regimes

LABEL = "REUSED_HISTORY_DIAGNOSTIC"


def select_train(rows: list[dict], baseline: str) -> dict:
    if not rows or any(r["partition"] != "train" or r["costs"] != "base" for r in rows):
        raise ValueError("Selection requires train/base only")
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
            "eligible_variants": [],
            "diagnostic": "INSUFFICIENT_DATA"
            if all(r["closed_trades"] < 40 for r in rows)
            else "REJECTED_TRAIN",
        }
    chosen = min(
        eligible,
        key=lambda r: (-r["sharpe"], r["max_drawdown_pct"], -r["profit_factor"], r["candidate"]),
    )
    return {
        "candidate": chosen["candidate"],
        "train_eligible": True,
        "eligible_variants": [r["candidate"] for r in eligible],
        "diagnostic": "TRAIN_ELIGIBLE",
    }


def regime_analysis(frame, result) -> dict:
    report = previous_regime_analysis(frame, result)
    labels = regimes(frame)
    for axis, rows in report["axes"].items():
        for label, row in rows.items():
            selected = [
                t
                for t in result.trades
                if labels.loc[t.signal_close - pd.Timedelta(hours=1), axis] == label
            ]
            gross = sum(t.quantity * (t.exit_reference - t.entry_reference) for t in selected)
            row["gross_pnl"] = gross
            row["gross_return_contribution_pct"] = gross / result.equity.iloc[0] * 100
            row["average_trade"] = row["expectancy"]
    return report


def monte_carlo(
    pnls: list[float], key: str, capital: float = 10000.0, simulations: int = 10000
) -> tuple[dict, dict]:
    if capital <= 0 or simulations < 1 or not np.isfinite(pnls).all():
        raise ValueError("Invalid simulation inputs")
    if len(pnls) < 30:
        return {"status": "INSUFFICIENT_DATA", "trades": len(pnls), "minimum": 30}, {}
    values = np.array(pnls, dtype=float)
    report = {
        "status": "completed",
        "trades": len(pnls),
        "methods": {},
        "assumptions": (
            "Fixed realized cash PnLs, independent accounts, no re-sizing or fills. "
            "Reshuffling leaves terminal return unchanged; bootstrap samples with replacement. "
            "IID trade sampling ignores regimes/dependence. Closed-trade DD, not "
            "intrabar DD; not a forecast. "
            "Paths below zero are retained as stress paths without bankruptcy absorption."
        ),
    }
    arrays = {}
    for method in ("reshuffling", "bootstrap"):
        seed = int.from_bytes(hashlib.sha256(f"{key}/{method}".encode()).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        samples = np.empty((simulations, 4))
        for start in range(0, simulations, 250):
            size = min(250, simulations - start)
            drawn = (
                np.array([rng.permutation(values) for _ in range(size)])
                if method == "reshuffling"
                else rng.choice(values, size=(size, len(values)))
            )
            equity = np.column_stack([np.full(size, capital), capital + drawn.cumsum(axis=1)])
            peaks = np.maximum.accumulate(equity, axis=1)
            dd = ((peaks - equity) / peaks).max(axis=1) * 100
            streak, longest = np.zeros(size, dtype=int), np.zeros(size, dtype=int)
            for col in drawn.T:
                streak = np.where(col < 0, streak + 1, 0)
                longest = np.maximum(longest, streak)
            terminal = np.full(size, values.sum()) if method == "reshuffling" else drawn.sum(axis=1)
            samples[start : start + size] = np.column_stack(
                [terminal / capital * 100, dd, longest, terminal]
            )
        arrays[method] = samples
        report["methods"][method] = {
            "seed": seed,
            "simulations": simulations,
            "percentiles": {
                name: dict(
                    zip(
                        ("5", "25", "50", "75", "95"),
                        np.percentile(samples[:, i], [5, 25, 50, 75, 95]).tolist(),
                        strict=True,
                    )
                )
                for i, name in enumerate(
                    ("return_pct", "drawdown_pct", "losing_streak", "terminal_pnl")
                )
            },
            "terminal_loss_probability_pct": float((samples[:, 0] < 0).mean() * 100),
            "nonpositive_equity_path_pct": float((samples[:, 1] >= 100).mean() * 100),
        }
    return report, arrays


def cost_analysis(rows: list[dict], selections: dict) -> dict:
    report = {}
    for name, choice in selections.items():
        report[name] = {}
        for partition in ("train", "validation", "test", "final_holdout"):
            group = {
                r["costs"]: r
                for r in rows
                if r["candidate"] == choice["candidate"]
                and r["partition"] == partition
                and r["benchmark_pct"] is None
            }
            if set(group) != {"zero", "base", "adverse"}:
                raise ValueError("All three independently executed cost scenarios required")
            fields = ("return_pct", "sharpe", "profit_factor", "max_drawdown_pct", "closed_trades")
            report[name][partition] = {
                "scenarios": {cost: {k: r[k] for k in fields} for cost, r in group.items()},
                "cost_drag_pct_points": group["zero"]["return_pct"] - group["base"]["return_pct"],
                "adverse_drag_pct_points": group["base"]["return_pct"]
                - group["adverse"]["return_pct"],
            }
    return {
        "interpretation": LABEL,
        "strategies": report,
        "convention": (
            "Drag is difference between complete reruns, including changed "
            "fills, sizes and trade counts."
        ),
    }
