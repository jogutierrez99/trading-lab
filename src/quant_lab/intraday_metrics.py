"""Opt-in descriptive diagnostics; no selection, tuning or eligibility decisions."""

from dataclasses import dataclass

from quant_lab.backtest import BacktestResult


@dataclass(frozen=True)
class DiagnosticResult(BacktestResult):
    diagnostics: dict


def diagnostic_result(result, candles, signals, segment, strategy, *, hours_per_bar=0.25):
    trades = result.trades
    gross = [
        (1 if t.side == "long" else -1) * t.quantity * (t.exit_reference - t.entry_reference)
        for t in trades
    ]
    fees = sum(t.entry_fee + t.exit_fee for t in trades)
    slippage = sum(t.slippage_cost for t in trades)
    spread = sum(t.spread_cost for t in trades)
    costs, gross_profit = fees + slippage + spread, sum(max(v, 0) for v in gross)
    profits = sorted((t.net_pnl for t in trades if t.net_pnl > 0), reverse=True)
    scored = [i for i, t in enumerate(candles.index) if segment.start <= t < segment.end]
    le = sum(signals.long_entries[i] for i in scored)
    se = sum(signals.short_entries[i] for i in scored)
    allowed = le if result.direction == "long" else se if result.direction == "short" else le + se
    n = len(trades)
    metrics = {
        "gross_price_pnl": sum(gross),
        "gross_return_pct": 100 * sum(gross) / result.equity.iloc[0],
        "total_modeled_costs": costs,
        "cost_gross_profit_ratio": costs / gross_profit if gross_profit else None,
        "average_trade": sum(t.net_pnl for t in trades) / n if n else None,
        "average_holding_hours": sum(t.holding_bars for t in trades) * hours_per_bar / n
        if n
        else None,
        "top_5_profit_share_pct": 100 * sum(profits[:5]) / sum(profits) if profits else None,
        "long_setup_count": le,
        "short_setup_count": se,
        "setups_traded_pct": 100 * n / allowed if allowed else None,
    }
    if strategy == "range_mean_reversion_v1":
        metrics |= {
            "midpoint_exit_pct": 100 * sum(t.reason == "target" for t in trades) / n if n else None,
            "regime_exit_losses": -sum(min(t.net_pnl, 0) for t in trades if t.reason == "signal"),
        }
    return DiagnosticResult(**result.__dict__, diagnostics=metrics)
