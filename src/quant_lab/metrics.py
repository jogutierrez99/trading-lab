"""Descriptive historical metrics; daily UTC returns, zero risk-free assumption."""

import math

import pandas as pd

from quant_lab.backtest import BacktestResult


def summarize(result: BacktestResult) -> dict:
    equity = result.equity
    pnl = [trade.net_pnl for trade in result.trades]
    gains = sum(v for v in pnl if v > 0)
    losses = -sum(v for v in pnl if v < 0)
    peaks = equity.cummax()
    fees = sum(t.entry_fee + t.exit_fee for t in result.trades)
    if result.open_position:
        fees += result.open_position["entry_fee"]
    returns = daily_returns(equity)
    days = (equity.index[-1] - equity.index[0]).total_seconds() / 86400
    volatility = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    downside = float((returns.clip(upper=0).pow(2).mean()) ** 0.5)
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1)
    drawdown = float(((peaks - equity) / peaks).max())
    cagr = (1 + total_return) ** (365 / days) - 1 if days and total_return > -1 else None
    values = {
        "direction": result.direction,
        "market_mode": result.market_mode,
        "starting_equity": float(equity.iloc[0]),
        "ending_equity": float(equity.iloc[-1]),
        "net_change": float(equity.iloc[-1] - equity.iloc[0]),
        "return_pct": float((equity.iloc[-1] / equity.iloc[0] - 1) * 100),
        "max_drawdown_pct": float(((peaks - equity) / peaks).max() * 100),
        "closed_trades": len(pnl),
        "win_rate_pct": 100 * sum(v > 0 for v in pnl) / len(pnl) if pnl else None,
        "profit_factor": gains / losses if losses else None,
        "profit_factor_note": None if losses else "undefined_without_losing_trades",
        "realized_net_pnl": sum(pnl),
        "fees_paid": fees,
        "rejected_entries": len(result.rejections),
        "has_open_position": result.open_position is not None,
        "observed_days": days,
        "cagr_pct": cagr * 100 if cagr is not None else None,
        "annualized_volatility_pct": volatility * math.sqrt(365) * 100,
        "sharpe": float(returns.mean()) / volatility * math.sqrt(365) if volatility else None,
        "sortino": float(returns.mean()) / downside * math.sqrt(365) if downside else None,
        "calmar": cagr / drawdown if drawdown and cagr is not None else None,
        "average_win": gains / sum(v > 0 for v in pnl) if gains else None,
        "average_loss": -losses / sum(v < 0 for v in pnl) if losses else None,
        "expectancy": sum(pnl) / len(pnl) if pnl else None,
        "average_holding_bars": sum(t.holding_bars for t in result.trades) / len(pnl)
        if pnl
        else None,
        "average_close_exposure_pct": float(result.exposure.iloc[1:].mean() * 100),
        "turnover_initial_equity": result.turnover / float(equity.iloc[0]),
        "slippage_cost_closed_trades": sum(t.slippage_cost for t in result.trades),
        "spread_cost_closed_trades": sum(t.spread_cost for t in result.trades),
        "funding_pnl": None,
        "funding_note": "not_applicable_spot"
        if result.market_mode == "spot"
        else "not_modelled_synthetic",
        "metric_conventions": "Daily UTC returns; sqrt(365); risk-free=0; undefined=null",
    }
    return {
        k: None if isinstance(v, float) and not math.isfinite(v) else v for k, v in values.items()
    }


def daily_returns(equity: pd.Series) -> pd.Series:
    # Engine timestamps label interval ENDS. Midnight belongs to the preceding day.
    closes = equity.iloc[1:].copy()
    closes.index = closes.index - pd.Timedelta(nanoseconds=1)
    daily = closes.resample("D").last()
    previous = daily.shift(1)
    if len(previous):
        previous.iloc[0] = equity.iloc[0]
    return daily / previous - 1
