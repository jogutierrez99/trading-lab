"""Predefined descriptive study analyses. These outputs never select trading rules."""

import itertools

import pandas as pd

from quant_lab.metrics import daily_returns

CLASSIFICATION = {
    "DIAGNOSTIC_ONLY": "Always; reused BTC and many descriptive comparisons, never ROBUST.",
    "CROSS_MARKET_PROMISING": (
        "At least one base-positive combination with PF>1, Sharpe>0 and>=30 trades in EACH asset."
    ),
    "ASSET_DEPENDENT": "One asset has any positive base combination and the other has none.",
    "TIMEFRAME_DEPENDENT": (
        "Median base return across assets is positive for at least one "
        "evaluated timeframe and nonpositive for another."
    ),
    "COST_SENSITIVE": (
        "At least one combination changes from positive zero to "
        "nonpositive base, or positive base to nonpositive adverse."
    ),
    "REGIME_DEPENDENT": (
        "At least one combination has both positive and negative trade PnL"
        " regimes with>=10 trades per regime on the same axis."
    ),
    "INSUFFICIENT_DATA": (
        "Any requested combination skipped or any evaluated base combination has<30 trades."
    ),
    "FAILED_GENERALIZATION": (
        "No ETH base combination has both positive return and PF>1 with>=30 trades."
    ),
}


def stability(annual):
    full = annual[annual.complete_calendar_year]
    if full.empty:
        return {"positive_year_ratio": None, "complete_years": 0}
    return {
        "positive_year_ratio": float((full.return_pct > 0).mean()),
        "negative_year_ratio": float((full.return_pct < 0).mean()),
        "worst_year": float(full.return_pct.min()),
        "best_year": float(full.return_pct.max()),
        "median_year": float(full.return_pct.median()),
        "return_std_across_years": float(full.return_pct.std(ddof=0)),
        "PF_median_year": finite_median(full.profit_factor),
        "Sharpe_median_year": finite_median(full.sharpe),
        "complete_years": len(full),
        "positive_years": int((full.return_pct > 0).sum()),
        "negative_years": int((full.return_pct < 0).sum()),
    }


def finite_median(series):
    values = series.dropna()
    return float(values.median()) if len(values) else None


def consistency(group, annual):
    positive = group.return_pct > 0
    market = group.groupby("asset").return_pct.median()
    tf = group.groupby("timeframe").return_pct.median()
    years = annual[annual.complete_calendar_year]
    return {
        "evaluated_combinations": len(group),
        "positive_combinations": int(positive.sum()),
        "pf_above_one": int((group.profit_factor > 1).sum()),
        "positive_sharpe": int((group.sharpe > 0).sum()),
        "sufficient_trades": int((group.closed_trades >= 30).sum()),
        "markets_positive_pct": float((market > 0).mean() * 100),
        "timeframes_positive_pct": float((tf > 0).mean() * 100),
        "combinations_positive_pct": float(positive.mean() * 100),
        "median_return": finite_median(group.return_pct),
        "median_sharpe": finite_median(group.sharpe),
        "median_profit_factor": finite_median(group.profit_factor),
        "median_max_dd": finite_median(group.max_drawdown_pct),
        "total_trades": int(group.closed_trades.sum()),
        "median_trades": finite_median(group.closed_trades),
        "positive_years": int((years.return_pct > 0).sum()),
        "negative_years": int((years.return_pct < 0).sum()),
        "positive_years_pct": float((years.return_pct > 0).mean() * 100) if len(years) else None,
        "negative_years_pct": float((years.return_pct < 0).mean() * 100) if len(years) else None,
        "denominators": (
            "Markets/timeframes use median evaluated return>0. Year counts are"
            " combination-years, not independent samples; partial years "
            "excluded. Trades overlap across independent accounts."
        ),
    }


def flags(group, cost, regimes, requested=6):
    result = ["DIAGNOSTIC_ONLY"]
    positive_assets = group.groupby("asset").return_pct.max() > 0
    eligible = group[
        (group.return_pct > 0)
        & (group.profit_factor > 1)
        & (group.sharpe > 0)
        & (group.closed_trades >= 30)
    ]
    if eligible.asset.nunique() == 2:
        result.append("CROSS_MARKET_PROMISING")
    if positive_assets.sum() == 1:
        result.append("ASSET_DEPENDENT")
    tf = group.groupby("timeframe").return_pct.median()
    if (tf > 0).any() and (tf <= 0).any():
        result.append("TIMEFRAME_DEPENDENT")
    if any(
        (c["zero_return"] > 0 >= c["base_return"]) or (c["base_return"] > 0 >= c["adverse_return"])
        for c in cost
    ):
        result.append("COST_SENSITIVE")
    for report in regimes:
        if any(
            any(r["trades"] >= 10 and r["trade_pnl"] > 0 for r in axis.values())
            and any(r["trades"] >= 10 and r["trade_pnl"] < 0 for r in axis.values())
            for axis in report.values()
        ):
            result.append("REGIME_DEPENDENT")
            break
    if len(group) < requested or (group.closed_trades < 30).any():
        result.append("INSUFFICIENT_DATA")
    eth = group[
        (group.asset == "ETHUSDT")
        & (group.return_pct > 0)
        & (group.profit_factor > 1)
        & (group.closed_trades >= 30)
    ]
    if eth.empty:
        result.append("FAILED_GENERALIZATION")
    return result


def cost_rows(rows):
    result = []
    for key, group in rows.groupby(["strategy", "asset", "timeframe", "partition"]):
        indexed = group.set_index("costs")
        if set(indexed.index) != {"zero", "base", "adverse"}:
            raise ValueError("Missing cost rerun")
        zero, base, adverse = (indexed.loc[c] for c in ("zero", "base", "adverse"))
        years = base.observed_days / 365
        result.append(
            dict(zip(("strategy", "asset", "timeframe", "partition"), key, strict=True))
            | {
                "trades_per_year": base.closed_trades / years,
                "costs_per_year": base.total_costs / years,
                "cost_per_trade": None
                if pd.isna(base.cost_per_trade)
                else float(base.cost_per_trade),
                "zero_to_base_drag": zero.return_pct - base.return_pct,
                "base_to_adverse_drag": base.return_pct - adverse.return_pct,
                "cost_drag_over_gross_profit": base.total_costs / base.gross_positive_trade_pnl
                if base.gross_positive_trade_pnl > 0
                else None,
                "zero_return": zero.return_pct,
                "base_return": base.return_pct,
                "adverse_return": adverse.return_pct,
                "denominator": (
                    "Sum of positive before-cost reference-price trade PnLs on BASE "
                    "fills, not net gross PnL; cash costs/positive gross profit. Drag "
                    "columns are percentage-point differences of full reruns."
                ),
            }
        )
    return result


def jaccard(a, b):
    return len(a & b) / len(a | b) * 100 if a | b else None


def overlaps(trades, timeframe):
    entries = {name: {t["entry_time"] for t in rows} for name, rows in trades.items()}
    holdings = {}
    for name, rows in trades.items():
        occupied = set()
        for t in rows:
            last = pd.Timestamp(t["exit_bar_open"])
            if t["exit_timing"] == "open":
                last -= pd.Timedelta(timeframe)
            occupied.update(pd.date_range(pd.Timestamp(t["entry_time"]), last, freq=timeframe))
        holdings[name] = occupied
    return [
        {
            "a": a,
            "b": b,
            "entry_jaccard_pct": jaccard(entries[a], entries[b]),
            "holding_bar_jaccard_pct": jaccard(holdings[a], holdings[b]),
        }
        for a, b in itertools.combinations(sorted(trades), 2)
    ]


def correlations(equities):
    returns = pd.DataFrame({name: daily_returns(equity) for name, equity in equities.items()})
    matrix = returns.corr(min_periods=30)
    return {
        "daily_observations": len(returns),
        "method": (
            "Pearson daily UTC account returns; cash-flat exclusions retained;"
            " undefined correlations=null."
        ),
        "matrix": {
            c: {r: None if pd.isna(v) else float(v) for r, v in matrix[c].items()} for c in matrix
        },
    }
