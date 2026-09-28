"""Reuse original hourly baseline and unchanged perpetual execution/risk models."""

from dataclasses import asdict

import pandas as pd

from quant_lab.execution_policies.optional_15m_fill import (
    BaselineEntry,
    OptionalFillPolicy,
    entry_identity,
    pair_record,
)
from quant_lab.mtf_execution import configuration, execute_window, prepare, settings
from quant_lab.mtf_features import STEPS
from quant_lab.new_mtf_features import contiguous_features


def quarter_features(quarter):
    f = contiguous_features(quarter, "15m")
    f["recovery"] = (f.close > f.previous_high) & (f.close > f.open)
    f["breakout"] = (f.close > f.small_high) & (f.close > f.open)
    f.index += STEPS["15m"]
    return f[["open", "high", "low", "close", "ema20", "recovery", "consolidation", "breakout"]]


def prepare_case(data, case):
    config = configuration(*case)
    baseline = prepare(data, config)
    timed = []
    for hourly, _mark, funding, _decisions, _hf in baseline:
        quarter = data["quarter"].loc[hourly.index[0] : hourly.index[-1] + 3 * STEPS["15m"]]
        expected = pd.date_range(hourly.index[0], hourly.index[-1] + 3 * STEPS["15m"], freq="15min")
        if not quarter.index.equals(expected):
            raise ValueError("Incomplete matched quarter block; refusing gap fill")
        f = quarter_features(quarter)
        decisions = pd.DataFrame(False, index=f.index, columns=["le", "se", "lx", "sx"])
        decisions["distance"] = 0.0
        timed.append((quarter, data["quarter_mark"].loc[quarter.index], funding, decisions, f))
    return config, baseline, timed


def baseline_run(prepared, start, end, costs, funding):
    config, baseline, _timed = prepared
    return execute_window(baseline, config, start, end, costs, settings().capital, funding)


def entry_stream(prepared, case, partition, scenario, trades):
    """Whitelist entry-time fields. Exit dates/outcomes are deliberately not read."""
    config, blocks, _timed = prepared
    features = pd.concat([b[4] for b in blocks])
    entries = []
    for trade in trades:
        if trade.side != "long":
            raise ValueError("This frozen experiment only admits LONG_ONLY")
        time = trade.entry_time
        row = features.loc[time - STEPS["1h"]]
        if not row.long_final:
            raise AssertionError("Baseline trade has no original hourly signal")
        family = case[1]
        level = (
            row.st_line
            if family == "supertrend_pullback"
            else row.kc_middle
            if family == "keltner_breakout"
            else row.channel_high
            if family == "roc_momentum"
            else row.ema50
        )
        retest = row.kc_upper if family == "keltner_breakout" else level
        signal_id, trade_id = entry_identity(case, partition, scenario, time)
        entries.append(
            BaselineEntry(
                trade_id,
                signal_id,
                trade.signal_close,
                time,
                trade.entry_price,
                float(row.risk_atr),
                float(row.risk_atr * config.risk.atr_multiplier),
                float(level),
                float(retest),
            )
        )
    if len({e.baseline_trade_id for e in entries}) != len(entries):
        raise AssertionError("Duplicate baseline mapping")
    return entries


def baseline_pairs(entries):
    return [
        pair_record(e)
        | {
            "status": "ENTERED",
            "fallback_used": True,
            "fallback_reason": "original_baseline",
            "experimental_entry_time": e.baseline_entry_time,
            "experimental_entry_price": e.baseline_entry_price,
            "fill_improvement_abs": 0.0,
            "fill_improvement_pct": 0.0,
            "fill_improvement_atr": 0.0,
            "wait_minutes": 0.0,
        }
        for e in entries
    ]


def optimized_run(prepared, case, entries, start, end, costs, funding):
    config, _baseline, timed = prepared
    config = config.model_copy(
        update={"market": config.market.model_copy(update={"timeframe": "15m"})}
    )
    policies = []

    def factory(features, left, right):
        policy = OptionalFillPolicy(features, entries, left, right, case[1], costs)
        policies.append(policy)
        return policy

    result, sides, events = execute_window(
        timed,
        config,
        start,
        end,
        costs,
        settings().capital,
        funding,
        execution_policy_factory=factory,
    )
    records = [r for p in policies for r in p.records]
    if {r["baseline_trade_id"] for r in records} != {e.baseline_trade_id for e in entries}:
        raise AssertionError("Missing baseline trade mapping")
    if len(records) != len(entries) or len([r for r in records if r["status"] == "ENTERED"]) != len(
        result.trades
    ):
        raise AssertionError("Duplicate or unlinked experimental trade")
    rejections = {r.time: r.reason for r in result.rejections}
    for record in records:
        if record["non_execution_reason"] == "engine_risk_rejection":
            matching = [
                str(reason)
                for time, reason in rejections.items()
                if record["baseline_entry_time"]
                <= time
                <= record["baseline_entry_time"] + STEPS["1h"]
            ]
            record["non_execution_reason"] += ":" + ";".join(matching)
    return result, sides, events, records


def serialize_entries(entries):
    return [asdict(e) for e in entries]


def restore_entries(rows):
    return [
        BaselineEntry(
            **(r | {k: pd.Timestamp(r[k]) for k in ("baseline_signal_time", "baseline_entry_time")})
        )
        for r in rows
    ]
