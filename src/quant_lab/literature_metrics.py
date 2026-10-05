"""Descriptive entry attribution; never ranking, optimization or promotion."""

import json
from dataclasses import replace

import pandas as pd

from quant_lab.intraday_metrics import DiagnosticResult
from quant_lab.study_data import HOURS
from quant_lab.study_excursions import entry_diagnostics


def excursions(result, candles, timeframe):
    """Reuse existing conservative bounds; mirror shorts as in Batch006 analysis."""
    records = []
    for trade in result.trades:
        subset = candles.loc[trade.entry_time : trade.exit_bar_open].copy()
        observed = trade
        if trade.side == "short":
            origin = 2 * trade.entry_reference
            old_high = subset.high.copy()
            subset["high"] = origin - subset.low
            subset["low"] = origin - old_high
            subset["open"] = origin - subset.open
            subset["close"] = origin - subset.close
            observed = replace(trade, side="long", exit_reference=origin - trade.exit_reference)
        quality, _, _ = entry_diagnostics(subset, replace(result, trades=(observed,)), timeframe)
        records.append(
            {
                key: quality["trades"][0][key]
                for key in (
                    "mfe_pct",
                    "mae_pct",
                    "mfe_upper_bound_pct",
                    "mae_upper_bound_pct",
                    "intrabar_censored",
                )
            }
        )
    return records


def enrich(result, strategy, candles, fractions):
    f = strategy.prepare_features(candles)
    entries = []
    buckets = {}
    bounds = excursions(result, candles, strategy.config.market.timeframe)
    for trade, bound in zip(result.trades, bounds, strict=True):
        time = trade.signal_close
        row = f.loc[time - pd.Timedelta(hours=HOURS[strategy.config.market.timeframe])]
        record = {"signal_close": str(time), "side": trade.side, "net_pnl": trade.net_pnl} | bound
        for field in ("momentum", "realized_volatility", "rsi", "adx"):
            if field in row:
                record[field] = float(row[field])
        if fractions is not None:
            record["scaling_pct"] = float(fractions.loc[row.name] * 100)
        strength = "long_strength" if trade.side == "long" else "short_strength"
        if strength in row:
            record["breakout_strength_atr"] = float(row[strength])
        if "rsi" in row:
            bucket = (
                "rsi_above_70" if row.rsi > 70 else "rsi_below_30" if row.rsi < 30 else "rsi_middle"
            )
        else:
            bucket = (
                "positive_momentum"
                if row.get("momentum", 1 if trade.side == "long" else -1) > 0
                else "negative_momentum"
            )
        summary = buckets.setdefault(bucket, {"trades": 0, "net_pnl": 0.0})
        summary["trades"] += 1
        summary["net_pnl"] += trade.net_pnl
        entries.append(record)
    extra = {
        "entry_diagnostics": entries,
        "entry_buckets": json.dumps(buckets, sort_keys=True),
        "mfe_mean_pct": sum(r["mfe_pct"] for r in bounds) / len(bounds) if bounds else None,
        "mae_mean_pct": sum(r["mae_pct"] for r in bounds) / len(bounds) if bounds else None,
    }
    for field, target in (
        ("momentum", "average_entry_momentum"),
        ("realized_volatility", "average_entry_volatility"),
        ("scaling_pct", "average_entry_scaling_pct"),
        ("rsi", "average_entry_rsi"),
        ("adx", "average_entry_adx"),
        ("breakout_strength_atr", "average_breakout_strength_atr"),
    ):
        values = [r[field] for r in entries if field in r]
        extra[target] = sum(values) / len(values) if values else None
    return DiagnosticResult(
        **{k: v for k, v in result.__dict__.items() if k != "diagnostics"},
        diagnostics=result.diagnostics | extra,
    )
