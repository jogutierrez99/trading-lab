"""Lab bridge to the existing hourly isolated-1x perpetual engine."""

import json

import numpy as np
import pandas as pd

from quant_lab.backtest import BacktestResult
from quant_lab.features import atr
from quant_lab.intraday_metrics import DiagnosticResult, diagnostic_result
from quant_lab.perpetual_execution import FuturesAssumptions, run_perpetual
from quant_lab.study_execution import continuous_blocks


def funding_inputs(candles, funding, parameters):
    p = parameters
    # Quantiles use only preceding events; ties have a midrank descriptive percentile.
    previous = funding.rate.shift(1).rolling(p.funding_window, min_periods=p.funding_window)
    events = pd.DataFrame(
        {
            "funding_rate": funding.rate,
            "funding_low": previous.quantile(p.lower_quantile),
            "funding_high": previous.quantile(1 - p.lower_quantile),
            "known_at": funding.index,
        },
        index=funding.index,
    )
    rank = []
    rates = funding.rate.to_numpy()
    for i, v in enumerate(rates):
        prior = rates[max(0, i - p.funding_window) : i]
        rank.append(
            float(((prior < v).sum() + 0.5 * (prior == v).sum()) / len(prior))
            if len(prior) == p.funding_window
            else np.nan
        )
    events["funding_percentile"] = rank
    closes = candles.index + pd.Timedelta(hours=1)
    aligned = events.reindex(closes, method="ffill")
    aligned["funding_age_hours"] = (closes - aligned.known_at).dt.total_seconds() / 3600
    aligned.index = candles.index
    return candles.join(aligned)


def execute(candles, strategy, segment, app, risk, execution, aux, common_days):
    usable = candles.loc[candles.index.floor("D").isin(common_days)]
    balance = app.starting_capital
    trades = []
    rejections = []
    equities = []
    exposures = []
    turnover = 0.0
    feature_parts = []
    signal_parts = []
    for block in continuous_blocks(usable, "1h"):
        left = max(segment.start, block.index[0])
        right = min(segment.end, block.index[-1] + pd.Timedelta(hours=1))
        if left >= right:
            continue
        source = block.loc[block.index < right]
        enriched = funding_inputs(source, aux["funding"], strategy.parameters)
        f = strategy.prepare_features(enriched)
        sig = strategy.generate_signals(enriched)
        feature_parts.append(f)
        signal_parts.append((f.index, sig))
        decisions = pd.DataFrame(
            {
                "le": sig.long_entries,
                "lx": sig.long_exits,
                "se": sig.short_entries,
                "sx": sig.short_exits,
                "distance": atr(source, risk.atr_period) * risk.atr_multiplier,
            },
            index=source.index + pd.Timedelta(hours=1),
        )
        decisions = decisions.loc[(decisions.index > left) & (decisions.index < right)]
        runframe = source.loc[source.index >= left]
        result, _, _ = run_perpetual(
            runframe,
            aux["mark"].loc[runframe.index],
            aux["funding"].loc[(aux["funding"].index >= left) & (aux["funding"].index < right)],
            decisions,
            left,
            right,
            app.costs,
            risk,
            FuturesAssumptions(
                quantity_step=execution.quantity_step,
                min_quantity=execution.min_quantity,
                min_notional=execution.min_notional,
            ),
            balance,
            True,
            execution.direction,
        )
        balance = float(result.equity.iloc[-1])
        trades.extend(result.trades)
        rejections.extend(result.rejections)
        equities.append(result.equity)
        exposures.append(result.exposure)
        turnover += result.turnover
    clock = pd.date_range(segment.start, segment.end, freq="h")

    def combine(parts, initial, carry):
        if not parts:
            return pd.Series(initial, index=clock, dtype=float)
        s = pd.concat(parts)
        s = s[~s.index.duplicated(keep="last")]
        s.loc[segment.start] = initial
        s = s.sort_index().reindex(clock)
        return s.ffill() if carry else s.fillna(0)

    result = BacktestResult(
        tuple(trades),
        combine(equities, app.starting_capital, True),
        tuple(rejections),
        None,
        execution.direction,
        "perpetual",
        combine(exposures, 0.0, False),
        turnover,
    )
    from quant_lab.strategies.base import Signals

    all_features = pd.concat(feature_parts) if feature_parts else candles.iloc[:0].copy()
    arrays = [[], [], [], []]
    for _, sig in signal_parts:
        for target, values in zip(
            arrays,
            (sig.long_entries, sig.long_exits, sig.short_entries, sig.short_exits),
            strict=True,
        ):
            target.extend(values)
    diagnostic = diagnostic_result(
        result,
        all_features,
        Signals(*(tuple(a) for a in arrays)),
        segment,
        strategy.name,
        hours_per_bar=1,
    )
    cases = {
        key: {"trades": 0, "net_pnl": 0.0, "funding_pnl": 0.0}
        for key in (
            "negative_positive",
            "negative_negative",
            "positive_negative",
            "positive_positive",
        )
    }
    entries = []
    from quant_lab.literature_metrics import excursions

    bounds = excursions(result, usable, "1h")
    for trade, bound in zip(trades, bounds, strict=True):
        key = trade.signal_close - pd.Timedelta(hours=1)
        row = all_features.loc[key]
        label = row.conditional_case
        cases[label]["trades"] += 1
        cases[label]["net_pnl"] += trade.net_pnl
        cases[label]["funding_pnl"] += trade.funding_pnl
        entries.append(
            {
                "signal_close": str(trade.signal_close),
                "case": label,
                "funding_rate": float(row.funding_rate),
                "funding_percentile": float(row.funding_percentile),
                "momentum": float(row.momentum),
                "side": trade.side,
                "net_pnl": trade.net_pnl,
                **bound,
            }
        )
    extra = {
        "funding_pnl": sum(t.funding_pnl for t in trades),
        "funding_note": "funding_included_in_PnL; settlement availability assumed; "
        "publication latency unknown",
        "funding_events": sum(t.funding_events for t in trades),
        "liquidation_fees": sum(t.liquidation_fee for t in trades),
        "bankruptcy_adjustment": sum(t.bankruptcy_adjustment for t in trades),
        "conditional_results": json.dumps(cases, sort_keys=True),
        "entry_diagnostics": entries,
        "matched_hours": len(
            usable.loc[(usable.index >= segment.start) & (usable.index < segment.end)]
        ),
        "excluded_hours": len(clock)
        - 1
        - len(usable.loc[(usable.index >= segment.start) & (usable.index < segment.end)]),
        "margin_model": "ISOLATED_1X_RESEARCH_ASSUMPTION",
        "mfe_mean_pct": sum(r["mfe_pct"] for r in bounds) / len(bounds) if bounds else None,
        "mae_mean_pct": sum(r["mae_pct"] for r in bounds) / len(bounds) if bounds else None,
    }
    return DiagnosticResult(**result.__dict__, diagnostics=diagnostic.diagnostics | extra)
