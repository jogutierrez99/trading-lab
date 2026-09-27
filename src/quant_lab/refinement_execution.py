"""Reuse frozen MTF signal rules and accounting, adding an optional entry policy."""

import pandas as pd

from quant_lab.mtf_execution import configuration, execute_window, prepare, settings
from quant_lab.mtf_features import STEPS, base_setup, closed_features, regime
from quant_lab.refinement_policy import ExecutionPolicy, diagnostics
from quant_lab.strategies.registry import StrategyRegistry

CASES = (
    ("BTCUSDT", "donchian", "V2"),
    ("BTCUSDT", "ema_adx", "V2"),
    ("ETHUSDT", "ema_adx", "V2"),
    ("BTCUSDT", "bollinger", "V4"),
)


def prepare_case(data, asset, family, baseline):
    config = configuration(asset, family, baseline)
    blocks = prepare(data, config)
    refined = []
    for source, mark, funding, decisions, frame in blocks:
        step = STEPS[config.market.timeframe]
        times = source.index + step
        hourly = data["frames"]["1h"].loc[source.index[0] : source.index[-1]]
        hstrategy = StrategyRegistry().discover().create(configuration(asset, family, "V2"))
        hf = hstrategy.prepare_features(hourly)
        valid = base_setup(hf, family, "long")
        hr = regime(closed_features(hourly, "1h", "4h"), family, "long")
        hf["setup_valid"] = valid
        hf["regime_valid"] = hr
        hf.index = hf.index + STEPS["1h"]
        aligned = hf.reindex(times, method="ffill")
        features = frame.copy()
        features.index = times
        features["new_signal"] = hf.long_final.reindex(times, fill_value=False).fillna(False)
        for column in ("setup_valid", "regime_valid"):
            features[column] = aligned[column].eq(True)
        features["origin_price"] = aligned.close
        features["origin_reference"] = (
            aligned.middle if family == "bollinger" else aligned.channel_high
        )
        features["origin_atr"] = aligned.atr
        features["execution_trigger"] = frame.long_raw.to_numpy()
        age = frame.long_middle_touch_age if family == "bollinger" else frame.long_ema_touch_age
        features["touch_open"] = source.index - pd.to_timedelta(
            age.to_numpy() * step.total_seconds(), unit="s"
        )
        refined.append((source, mark, funding, decisions, features))
    return config, blocks, refined


def run_case(prepared, asset, family, version, start, end, costs, include_funding=True):
    config, baseline, refined = prepared
    policies = []

    def factory(features, left, right):
        policy = ExecutionPolicy(features, left, right, asset, family, version)
        policies.append(policy)
        return policy

    is_refined = version.endswith(".1")
    result, sides, events = execute_window(
        refined if is_refined else baseline,
        config,
        start,
        end,
        costs,
        settings().capital,
        include_funding,
        execution_policy_factory=factory if is_refined else None,
    )
    stats, signals, lifecycle = diagnostics(policies)
    if is_refined:
        if stats["signals_executed"] != len(result.trades):
            raise AssertionError("Unlinked trade")
        if (
            stats["signals_generated"]
            != stats["signals_consumed"] + stats["signals_expired"] + stats["signals_invalidated"]
        ):
            raise AssertionError("Unfinished signal lifecycle")
    else:
        # Baseline instrumentation is observational only. No new policy is applied.
        step = STEPS[config.market.timeframe]
        signals = []
        for source, _m, _fu, decisions, features in baseline:
            mask = (decisions.index > start) & (decisions.index < end) & decisions["le"]
            for time in decisions.index[mask]:
                signals.append(
                    {
                        "signal_id": f"{asset}|{family}|{version}|{time}",
                        "signal_timestamp": time,
                        "direction": "long",
                        "signal_price": source.loc[time - step, "close"],
                        "signal_reference_level": None,
                        "regime_state": "LONG",
                        "expiry_timestamp": time,
                        "atr": features.loc[time - step, "risk_atr"],
                        "status": "expired",
                        "consumed": False,
                        "invalidated": False,
                        "expiry_reason": "not_filled_at_next_open",
                        "entry_time": None,
                        "signal_age": None,
                        "time_to_entry": None,
                        "entry_distance_atr": None,
                    }
                )
        trades = {t.entry_time: t for t in result.trades}
        for record in signals:
            t = trades.get(record["signal_timestamp"])
            if t:
                record.update(
                    status="consumed",
                    consumed=True,
                    expiry_reason=None,
                    entry_time=t.entry_time,
                    signal_age=0.0,
                    time_to_entry=0.0,
                    entry_distance_atr=abs(t.entry_price - record["signal_price"]) / record["atr"],
                )
        stats = {key: None for key in stats}
        stats.update(
            signals_generated=len(signals),
            signals_executed=len(result.trades),
            signals_consumed=len(result.trades),
            signals_expired=len(signals) - len(result.trades),
            signals_invalidated=0,
            trades_per_signal=len(result.trades) / len(signals) if signals else None,
        )
        lifecycle = [
            {
                "time": r["signal_timestamp"],
                "signal_id": r["signal_id"],
                "action": "BASELINE_OBSERVATION",
                "reason": r["status"],
            }
            for r in signals
        ]
    return result, sides, events, stats, signals, lifecycle
