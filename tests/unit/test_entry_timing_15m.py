"""Causality, opportunity lifecycle, inherited accounting and paired criteria."""

from dataclasses import FrozenInstanceError, asdict

import numpy as np
import pandas as pd
import pytest

from quant_lab.batch_006 import persist
from quant_lab.config import CostsConfig, RiskConfig
from quant_lab.entry_timing_execution import CASES, align_features, prepare_case
from quant_lab.entry_timing_protocol import assert_numerical, compare_baseline, measure
from quant_lab.entry_timing_reporting import classify
from quant_lab.execution_policies.timing_15m import TimingPolicy, timing_metrics
from quant_lab.experiments import ExperimentStore
from quant_lab.mtf_clock import execute
from quant_lab.mtf_execution import configuration
from quant_lab.mtf_features import complete_bars
from quant_lab.strategies.registry import StrategyRegistry


def policy(family="supertrend_pullback", architecture="V2", n=10):
    times = pd.date_range("2020-01-02", periods=n, freq="15min", tz="UTC")
    frame = pd.DataFrame(
        {
            "new_signal": False,
            "origin_price": 100.0,
            "origin_atr": 2.0,
            "structure_level": 97.0,
            "regime_valid": True,
            "structure_valid": True,
            "close": 100.0,
            "touch": False,
            "recovery": False,
            "consolidation": False,
            "breakout": False,
        },
        index=times,
    )
    frame.loc[times[0], "new_signal"] = True
    return TimingPolicy(
        frame,
        times[0] - pd.Timedelta(minutes=15),
        times[-1] + pd.Timedelta(minutes=15),
        "ETHUSDT",
        family,
        architecture,
    ), times


def test_immutable_signal_pullback_recovery_once():
    p, t = policy()
    assert p.decision(t[0], 100, False) is None
    snapshot = p.active[0]
    with pytest.raises(FrozenInstanceError):
        snapshot.signal_atr = 9
    p.rows[t[1]].update(touch=True, recovery=True)
    assert p.decision(t[1], 100, False) is None
    p.rows[t[2]].update(recovery=True, origin_atr=999, origin_price=999)
    assert p.decision(t[2], 101, False)["distance"] == 4
    assert p.active[0] == snapshot
    p.on_entry(t[2], 101)
    p.on_exit(t[2])
    for time in t[3:]:
        p.rows[time].update(touch=True, recovery=True)
        assert p.decision(time, 100, False) is None
    assert [e["status"] for e in p.events] == ["CREATED", "WAITING", "ENTERED", "CONSUMED"]
    assert p.records[0]["minutes_waited"] == 30
    assert p.records[0]["signal_atr"] == 2
    assert timing_metrics(p.records)["signals_entered"] == 1


@pytest.mark.parametrize("family", ["supertrend_pullback", "roc_momentum"])
def test_expiry_fourth_bar_and_no_fifth_entry(family):
    p, t = policy(family)
    for time in t[:5]:
        assert p.decision(time, 100, False) is None
    assert p.records[0]["status"] == "EXPIRED"
    p.rows[t[5]].update(recovery=True, touch=True, consolidation=True, breakout=True)
    assert p.decision(t[5], 100, False) is None


@pytest.mark.parametrize("architecture", ["V1", "V2"])
def test_roc_requires_three_post_signal_bars_then_fourth_close(architecture):
    p, t = policy("roc_momentum", architecture)
    for time in t[:5]:
        p.rows[time].update(consolidation=True, breakout=True)
        decision = p.decision(time, 100, False)
        assert (decision is not None) == (time == t[4])
    p.on_entry(t[4], 100)
    assert p.records[0]["bars_waited_15m"] == 4
    assert p.records[0]["regime_state"] == ("LONG" if architecture == "V2" else "NOT_APPLICABLE")


@pytest.mark.parametrize("family", ["supertrend_pullback", "roc_momentum"])
@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("regime_valid", False, "original_regime"),
        ("structure_valid", False, "original_structure"),
        ("close", 96.0, "original_structure"),
        ("close", 103.01, "extension"),
    ],
)
def test_invalidation(family, field, value, reason):
    p, t = policy(family)
    p.decision(t[0], 100, False)
    p.rows[t[1]][field] = value
    assert p.decision(t[1], 100, False) is None
    assert p.records[0]["status"] == "INVALIDATED"
    assert p.records[0]["reason"] == reason


def test_open_extension_gap_end_rejection_and_busy_position():
    p, t = policy()
    p.decision(t[0], 100, False)
    p.decision(t[1], 103.01, False)
    assert timing_metrics(p.records)["signals_blocked_extension"] == 1
    p, t = policy()
    p.decision(t[0], 100, False)
    p.decision(t[2], 100, False)
    assert p.records[0]["reason"] == "gap"
    p, t = policy()
    p.decision(t[0], 100, False)
    p.finalize(t[1], "window_end")
    assert p.records[0]["reason"] == "window_end"
    p, t = policy()
    p.decision(t[0], 100, True)
    assert p.records[0]["status"] == "INVALIDATED"
    p, t = policy()
    p.decision(t[0], 100, False)
    p.rows[t[1]]["touch"] = True
    p.decision(t[1], 100, False)
    p.rows[t[2]]["recovery"] = True
    assert p.decision(t[2], 100, False)
    p.decision(t[3], 100, False)  # no on_entry means engine rejected sizing
    assert p.records[0]["reason"] == "entry_rejected_by_engine"


def test_no_original_signal_no_entry_and_price_pairing_is_exact():
    p, t = policy()
    p.rows[t[0]]["new_signal"] = False
    for time in t:
        p.rows[time].update(touch=True, recovery=True)
        assert p.decision(time, 100, False) is None
    assert not p.records
    r = {
        "signal_id": "same",
        "status": "CONSUMED",
        "entry_price": 99.0,
        "minutes_waited": 30,
        "distance_from_signal_atr": 0.5,
        "reason": None,
    }
    assert timing_metrics([r], {"different": 100})["average_fill_improvement_pct"] is None
    assert timing_metrics([r], {"same": 100})["average_fill_improvement_pct"] == 1


def candles(n=1600):
    index = pd.date_range("2020", periods=n, freq="15min", tz="UTC")
    t = np.arange(n)
    price = 100 + t * 0.008 + 3 * np.sin(t / 32)
    return pd.DataFrame(
        {
            "open": price - 0.1,
            "high": price + 0.4,
            "low": price - 0.4,
            "close": price,
            "volume": 1.0,
        },
        index=index,
    )


@pytest.mark.parametrize("case", CASES)
def test_closed_quarter_hour_and_fourhour_prefix_invariance(case):
    quarter = candles()
    hourly = complete_bars(quarter, "15m", "1h")
    strategy = StrategyRegistry().discover().create(configuration(*case))
    full = align_features(hourly, quarter, strategy.prepare_features(hourly), case[1], case[2])
    for n in (127, 837, 1591):
        q = quarter.iloc[:n]
        h = complete_bars(q, "15m", "1h")
        prefix = align_features(h, q, strategy.prepare_features(h), case[1], case[2])
        pd.testing.assert_frame_equal(prefix, full.iloc[:n])
    assert not full.loc[full.index.minute != 0, "new_signal"].any()
    if case[2] == "V1":
        assert full.regime_valid.iloc[3:].all()
    # Alter data whose candle has not closed yet: no decision before its close changes.
    mutated = quarter.copy()
    mutated.iloc[839:, :4] *= 5
    h = complete_bars(mutated, "15m", "1h")
    other = align_features(h, mutated, strategy.prepare_features(h), case[1], case[2])
    pd.testing.assert_frame_equal(full.iloc[:839], other.iloc[:839])


def test_prepare_rejects_missing_quarters_without_mutation():
    q = candles(200)
    h = complete_bars(q, "15m", "1h")
    data = {
        "frames": {"1h": h},
        "mark": h,
        "quarter": q.drop(q.index[30]),
        "quarter_mark": q,
        "funding": pd.DataFrame({"rate": []}, index=pd.DatetimeIndex([], tz="UTC")),
    }
    with pytest.raises(ValueError, match="Incomplete matched quarter"):
        prepare_case(data, *CASES[0])
    assert len(h) == 50 and len(q) == 200


def engine_result():
    p, times = policy(n=300)
    p.rows[times[1]]["touch"] = True
    p.rows[times[2]]["recovery"] = True
    idx = pd.date_range(p.left, periods=301, freq="15min")
    frame = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0}, index=idx
    )
    fund = pd.DataFrame(
        {"rate": [0.001]}, index=pd.DatetimeIndex([times[4] + pd.Timedelta(milliseconds=47)])
    )
    decisions = pd.DataFrame(
        {"le": False, "se": False, "lx": False, "sx": False, "distance": 4.0}, index=idx
    )
    result, sides, events = execute(
        frame,
        frame,
        fund,
        decisions,
        p.left,
        p.right,
        CostsConfig(trading_fee_pct=0.05, slippage_pct=0.02, spread_pct=0.01),
        RiskConfig(risk_per_trade_pct=0.5, take_profit_enabled=False, max_holding_bars=72),
        direction="long",
        timeframe="15m",
        execution_policy=p,
    )
    return p, times, result, sides, events


def test_next_open_real_clock_funding_cost_risk_and_72_hour_limit():
    p, t, result, sides, events = engine_result()
    (trade,) = result.trades
    assert trade.entry_time == t[2] and trade.signal_close == t[2]
    assert trade.exit_time - trade.entry_time == pd.Timedelta(hours=72)
    assert trade.quantity * trade.entry_price + trade.entry_fee <= 2500 + 1e-6
    assert trade.expected_stop_loss <= trade.risk_budget <= 50
    assert trade.entry_fee == pytest.approx(trade.entry_price * trade.quantity * 0.0005)
    assert trade.funding_pnl == pytest.approx(-trade.quantity * 100 * 0.001)
    assert events[0]["time"] == t[4] + pd.Timedelta(milliseconds=47)
    assert result.equity.iloc[-1] == pytest.approx(10000 + trade.net_pnl)
    assert p.records[0]["status"] == "CONSUMED" and sides.ne(0).any()


def test_baseline_numerical_artifacts_and_explicit_abort(tmp_path):
    p, _t, result, sides, events = engine_result()
    values, _ = measure(result, sides, p.left, p.right, "timing", True)
    store = ExperimentStore(tmp_path, {}, {})
    for folder in ("equity", "trades"):
        (store.path / folder).mkdir()
    identifier = store.start({})
    persist(
        store,
        identifier,
        result,
        sides,
        {
            "metrics": values,
            "trades": [asdict(t) for t in result.trades],
            "funding_events": events,
            "rejections": [asdict(r) for r in result.rejections],
        },
    )
    reference = {"experiment_id": identifier}
    assert (
        compare_baseline(store.path, reference, result, sides, values, events)["status"]
        == "reproduced"
    )
    with pytest.raises(ValueError, match="Baseline reproduction mismatch"):
        compare_baseline(
            store.path, reference, result, sides, values | {"closed_trades": 2}, events
        )
    with pytest.raises(ValueError, match="Baseline reproduction mismatch"):
        compare_baseline(store.path, reference, result, sides + 1, values, events)
    assert_numerical({"value": 1.0 + 1e-10}, {"value": 1.0})
    with pytest.raises(ValueError, match="mismatch"):
        assert_numerical([], [1])


def classification_values():
    return {
        "return_pct": 20.0,
        "max_drawdown_pct": 10.0,
        "profit_factor": 1.4,
        "expectancy": 2.0,
        "closed_trades": 100,
        "total_costs": 500.0,
        "signal_execution_rate": 0.5,
    }


def test_known_low_execution_failure_survives_undefined_holdout():
    b = classification_values()
    t = b | {"signal_execution_rate": 0.09}
    missing = b | {"expectancy": None}
    result = classify(b, t, missing, missing, b, t, 12, 12)
    assert result["classification"] == "TIMING_WORSE"
    assert "low_execution_without_quality" in result["reasons"]


def test_relative_return_limit_not_percentage_points_and_classification():
    b = classification_values()
    t = b | {"expectancy": 3.0, "return_pct": 18.0}
    assert classify(b, t, b, t, b, t, 12, 10)["classification"] == "TIMING_IMPROVED"
    assert (
        classify(b, t | {"return_pct": 17.99}, b, t, b, t, 12, 10)["classification"]
        == "TIMING_MIXED"
    )
    assert classify(b, t, b, t, b, t, 12, 7)["classification"] == "TIMING_WORSE"
    assert classify(b, t | {"closed_trades": 29}, b, t, b, t, 12, 10)["sample_warning"]
    assert (
        classify(b, t | {"expectancy": None}, b, t, b, t, 12, 10)["classification"]
        == "TIMING_MIXED"
    )
    assert (
        classify(b, t, b, t | {"expectancy": 1.5}, b, t, 12, 10)["classification"] == "TIMING_WORSE"
    )
