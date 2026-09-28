"""Translate immutable hourly opportunities onto the existing quarter execution clock."""

from functools import partial

import pandas as pd

from quant_lab.execution_policies.timing_15m import TimingPolicy, opportunity, record_for
from quant_lab.mtf_execution import configuration, execute_window, prepare, settings
from quant_lab.mtf_features import STEPS, closed_features
from quant_lab.new_mtf_features import contiguous_features, higher_regime

CASES = (
    ("ETHUSDT", "supertrend_pullback", "V2"),
    ("ETHUSDT", "roc_momentum", "V2"),
    ("ETHUSDT", "roc_momentum", "V1"),
)


def align_features(hourly, quarter, hf, family, architecture):
    """Index each observation by availability, never by its source candle open."""
    h = hf.copy()
    h["origin_price"], h["origin_atr"] = h.close, h.risk_atr
    h["structure_level"] = h.st_line if family == "supertrend_pullback" else h.channel_high
    h["structure_valid"] = (
        h.st_trend if family == "supertrend_pullback" else (h.roc20 > 0) & (h.roc5 > h.roc20)
    )
    h["regime_valid"] = True
    if architecture == "V2":
        higher = closed_features(hourly, "1h", "4h", partial(contiguous_features, tf="4h"))
        h["regime_valid"] = higher_regime(higher, family).eq(True)
    h.index += STEPS["1h"]
    q = contiguous_features(quarter, "15m")
    q["touch"] = ((q.low <= q.ema20) & (q.high >= q.ema20)) | (
        (q.st_direction == 1) & (q.low <= q.st_line) & (q.high >= q.st_line)
    )
    q["recovery"] = (q.close > q.previous_high) & (q.close > q.open)
    q["breakout"] = (q.close > q.small_high) & (q.close > q.open)
    q.index += STEPS["15m"]
    # Engine calls at open T: q[T] is the bar that CLOSED at T.
    aligned = h.reindex(q.index, method="ffill")
    for name in (
        "origin_price",
        "origin_atr",
        "structure_level",
        "structure_valid",
        "regime_valid",
    ):
        q[name] = aligned[name]
    for name in ("structure_valid", "regime_valid"):
        q[name] = q[name].eq(True)
    q["new_signal"] = h.long_final.reindex(q.index, fill_value=False).eq(True)
    return q[
        [
            "new_signal",
            "origin_price",
            "origin_atr",
            "structure_level",
            "structure_valid",
            "regime_valid",
            "close",
            "touch",
            "recovery",
            "consolidation",
            "breakout",
        ]
    ]


def prepare_case(data, asset, family, architecture):
    config = configuration(asset, family, architecture)
    baseline = prepare(data, config)
    timed = []
    for hourly, _mark, funding, _decisions, hf in baseline:
        quarter = data["quarter"].loc[hourly.index[0] : hourly.index[-1] + 3 * STEPS["15m"]]
        expected = pd.date_range(hourly.index[0], hourly.index[-1] + 3 * STEPS["15m"], freq="15min")
        if not quarter.index.equals(expected):
            raise ValueError("Incomplete matched quarter segment; no implicit gap filling")
        features = align_features(hourly, quarter, hf, family, architecture)
        decisions = pd.DataFrame(False, index=features.index, columns=["le", "se", "lx", "sx"])
        decisions["distance"] = features.origin_atr * config.risk.atr_multiplier
        timed.append(
            (quarter, data["quarter_mark"].loc[quarter.index], funding, decisions, features)
        )
    return config, baseline, timed


def run_case(prepared, case, variant, start, end, costs, include_funding):
    config, baseline, timed = prepared
    policies = []

    def factory(features, left, right):
        policy = TimingPolicy(features, left, right, *case)
        policies.append(policy)
        return policy

    if variant == "timing":
        config = config.model_copy(
            update={"market": config.market.model_copy(update={"timeframe": "15m"})}
        )
    result, sides, events = execute_window(
        timed if variant == "timing" else baseline,
        config,
        start,
        end,
        costs,
        settings().capital,
        include_funding,
        execution_policy_factory=factory if variant == "timing" else None,
    )
    records, lifecycle = [], []
    if variant == "timing":
        records = [r for p in policies for r in p.records]
        lifecycle = [e for p in policies for e in p.events]
    else:
        trades = {t.entry_time: t for t in result.trades}
        for source, _m, _f, _d, features in timed:
            left, right = max(start, source.index[0]), min(end, source.index[-1] + STEPS["15m"])
            for time, row in features.loc[
                features.new_signal & (features.index > left) & (features.index < right)
            ].iterrows():
                signal = opportunity(*case, time, row)
                record = record_for(signal)
                trade = trades.get(time)
                record.update(
                    status="CONSUMED" if trade else "EXPIRED",
                    reason=None if trade else "baseline_not_filled",
                )
                if trade:
                    record.update(
                        entry_time=time,
                        entry_price=trade.entry_price,
                        bars_waited_15m=0,
                        minutes_waited=0,
                        distance_from_signal_atr=abs(
                            trade.entry_price - signal.signal_reference_price
                        )
                        / signal.signal_atr,
                    )
                records.append(record)
                lifecycle.append(
                    {
                        "signal_id": signal.signal_id,
                        "time": time,
                        "status": record["status"],
                        "reason": record["reason"],
                    }
                )
    entered = [r for r in records if r["status"] == "CONSUMED"]
    if len(entered) != len(result.trades) or len({r["signal_id"] for r in records}) != len(records):
        raise AssertionError("Unlinked or duplicate original signal/trade")
    if any(r["status"] not in {"CONSUMED", "EXPIRED", "INVALIDATED"} for r in records):
        raise AssertionError("Unfinished opportunity lifecycle")
    return result, sides, events, records, lifecycle
