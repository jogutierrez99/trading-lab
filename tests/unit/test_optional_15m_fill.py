"""Causal fallbacks and unchanged risk: synthetic fixtures only."""

from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from quant_lab.config import CostsConfig, RiskConfig
from quant_lab.execution_policies.optional_15m_fill import (
    BaselineEntry,
    OptionalFillPolicy,
    fill_metrics,
)
from quant_lab.mtf_clock import execute
from quant_lab.mtf_execution import configuration
from quant_lab.mtf_features import complete_bars
from quant_lab.optional_fill_execution import (
    baseline_run,
    entry_stream,
    optimized_run,
    prepare_case,
    quarter_features,
)
from quant_lab.optional_fill_protocol import APPROVED, load_protocol
from quant_lab.optional_fill_reporting import classify
from quant_lab.strategies.registry import StrategyRegistry


def policy(family="ema_adx", n=12, costs=None):
    times = pd.date_range("2020-01-02", periods=n, freq="15min", tz="UTC")
    features = pd.DataFrame(
        {
            "open": 98.0,
            "close": 99.0,
            "low": 98.0,
            "high": 100.0,
            "ema20": 99.0,
            "recovery": True,
            "consolidation": True,
            "breakout": True,
        },
        index=times,
    )
    entry = BaselineEntry("trade-1", "signal-1", times[0], times[0], 100.0, 2.0, 4.0, 90.0, 98.5)
    return (
        OptionalFillPolicy(
            features,
            [entry],
            times[0] - pd.Timedelta(minutes=15),
            times[-1] + pd.Timedelta(minutes=15),
            family,
            costs or CostsConfig(trading_fee_pct=0.0, slippage_pct=0.0, spread_pct=0.0),
        ),
        times,
        entry,
    )


@pytest.mark.parametrize(
    "family,age",
    [
        ("ema_adx", 1),
        ("trend_pullback", 1),
        ("supertrend_pullback", 2),
        ("keltner_breakout", 1),
        ("roc_momentum", 4),
    ],
)
def test_family_uses_first_causal_better_fill_and_never_duplicates(family, age):
    p, times, entry = policy(family)
    with pytest.raises(FrozenInstanceError):
        entry.baseline_entry_price = 101
    for time in times[:age]:
        assert p.decision(time, 99.0, False) is None
    assert p.decision(times[age], 99.0, False)["distance"] == 4
    p.on_entry(times[age], 99.0)
    p.on_exit(times[age])
    for time in times[age + 1 :]:
        assert p.decision(time, 98.0, False) is None
    (r,) = p.records
    assert r["optimized_entry_used"] and not r["fallback_used"]
    assert r["baseline_trade_id"] == "trade-1" and r["signal_id"] == "signal-1"
    assert r["fill_improvement_pct"] == 1.0
    assert r["fill_improvement_atr"] == 0.5
    assert r["wait_minutes"] == age * 15


@pytest.mark.parametrize("price", [100.0, 105.0])
@pytest.mark.parametrize(
    "family",
    ["ema_adx", "roc_momentum", "supertrend_pullback", "keltner_breakout", "trend_pullback"],
)
def test_no_improvement_fallback_is_current_open_not_original_entry(price, family):
    p, t, _entry = policy(family)
    for time in t[:4]:
        assert p.decision(time, price, False) is None
    assert p.decision(t[4], price, False)
    p.on_entry(t[4], price)
    (r,) = p.records
    assert r["fallback_used"] and not r["optimized_entry_used"]
    assert r["experimental_entry_time"] == t[4] != r["baseline_entry_time"]
    assert r["experimental_entry_price"] == price
    assert r["optimized_entry_time"] is None
    stats = fill_metrics(p.records)
    assert stats["trade_retention_rate"] == 1
    assert stats["number_of_worse_optimized_fills"] == 0
    assert stats["number_of_worse_fills"] == (price > 100)


def test_gap_open_below_structure_does_not_masquerade_as_optimized_fill():
    p, times, _entry = policy()
    for time in times[:4]:
        assert p.decision(time, 80, False) is None
    assert p.decision(times[4], 80, False)
    p.on_entry(times[4], 80)
    assert p.records[0]["fallback_used"]
    assert not p.records[0]["optimized_entry_used"]


def test_cost_adjusted_price_guard_and_failed_structure_never_cancel_fallback():
    p, t, _entry = policy(costs=CostsConfig(trading_fee_pct=0.0, slippage_pct=1.0, spread_pct=0.0))
    p.decision(t[0], 100, False)
    assert p.decision(t[1], 99.5, False) is None  # 100.495 after slippage, not better
    for time in t[2:4]:
        p.rows[time]["close"] = 80.0
        assert p.decision(time, 105, False) is None
    p.rows[t[4]]["close"] = 80.0
    assert p.decision(t[4], 105, False)
    p.on_entry(t[4], 106.05)
    assert p.records[0]["fallback_used"]


def test_segment_boundary_shortens_wait_and_explains_capacity_and_risk_loss():
    p, t, _entry = policy(n=2)
    p.decision(t[0], 105, False)
    assert p.decision(t[1], 105, False)
    p.on_entry(t[1], 105)
    assert p.records[0]["fallback_reason"] == "segment_or_window_boundary"
    p, t, _entry = policy()
    for time in t[:5]:
        assert p.decision(time, 105, True) is None
    assert p.records[0]["non_execution_reason"] == "position_capacity_at_deadline"
    assert fill_metrics(p.records)["retention_explanation_required"]
    p, t, _entry = policy()
    for time in t[:4]:
        p.decision(time, 105, False)
    assert p.decision(t[4], 105, False)
    p.finalize(t[5], "window_end")  # no on_entry: original sizing rejected
    assert p.records[0]["non_execution_reason"] == "engine_risk_rejection"


def test_rejected_optimization_can_retry_at_deadline_and_gap_is_audited():
    p, t, _entry = policy()
    p.decision(t[0], 100, False)
    assert p.decision(t[1], 99, False)
    for time in t[2:4]:
        assert p.decision(time, 101, False) is None
    assert p.decision(t[4], 101, False)
    p.on_entry(t[4], 101)
    assert p.records[0]["attempts"] == 2 and p.records[0]["fallback_used"]
    p, t, _entry = policy()
    p.decision(t[0], 100, False)
    p.decision(t[2], 100, False)
    assert p.records[0]["non_execution_reason"] == "unexpected_gap"


def test_pending_signal_is_not_a_new_opportunity_and_invalid_fill_is_rejected():
    p, t, _entry = policy()
    p.entries.clear()
    for time in t:
        assert p.decision(time, 99, False) is None
    assert not p.records
    p, t, _entry = policy()
    p.decision(t[0], 100, False)
    p.decision(t[1], 99, False)
    with pytest.raises(AssertionError, match="strictly improve"):
        p.on_entry(t[1], 100)


def candles(n=1600):
    idx = pd.date_range("2020", periods=n, freq="15min", tz="UTC")
    t = np.arange(n)
    prices = 100 + t * 0.005 + 3 * np.sin(t / 28)
    return pd.DataFrame(
        {
            "open": prices - 0.1,
            "high": prices + 0.4,
            "low": prices - 0.4,
            "close": prices,
            "volume": 1.0,
        },
        index=idx,
    )


def dataset(q):
    h = complete_bars(q, "15m", "1h")
    return {
        "frames": {"1h": h},
        "mark": h,
        "quarter": q,
        "quarter_mark": q,
        "funding": pd.DataFrame({"rate": []}, index=pd.DatetimeIndex([], tz="UTC")),
    }


@pytest.mark.parametrize("case", sorted(APPROVED))
def test_original_1h_4h_and_quarter_features_are_prefix_invariant(case):
    q = candles()
    h = complete_bars(q, "15m", "1h")
    strategy = StrategyRegistry().discover().create(configuration(*case))
    full = strategy.prepare_features(h)
    for n in (123, 317):
        pd.testing.assert_frame_equal(strategy.prepare_features(h.iloc[:n]), full.iloc[:n])
    f = quarter_features(q)
    pd.testing.assert_frame_equal(quarter_features(q.iloc[:837]), f.iloc[:837])
    changed = q.copy()
    changed.iloc[837:, :4] *= 10
    pd.testing.assert_frame_equal(quarter_features(changed).iloc[:837], f.iloc[:837])
    if case[-1] == "V1":
        assert "available_at_4h" not in full
    else:
        known = full.available_at_4h.dropna()
        assert (known <= known.index + pd.Timedelta(hours=1)).all()


def test_entry_stream_reads_no_future_trade_attributes():
    case = ("ETHUSDT", "ema_adx", "V2")
    q = candles(800)
    prepared = prepare_case(dataset(q), case)
    frame = prepared[1][0][4]
    time = frame.index[100] + pd.Timedelta(hours=1)
    frame.loc[time - pd.Timedelta(hours=1), "long_final"] = True
    # Object deliberately has no exit, future PnL, quantity or final equity fields.
    trade = SimpleNamespace(side="long", entry_time=time, signal_close=time, entry_price=100.0)
    entries = entry_stream(prepared, case, "train", "base", [trade])
    assert len(entries) == 1
    assert entries[0].baseline_entry_price == 100
    with pytest.raises(AssertionError, match="Duplicate"):
        entry_stream(prepared, case, "train", "base", [trade, trade])


def test_policy_prefix_invariance_ignores_later_cheaper_prices():
    p, times, _entry = policy()
    p.decision(times[0], 100, False)
    p.decision(times[1], 99, False)
    p.on_entry(times[1], 99)
    snapshot = p.records[0].copy()
    for t in times[2:]:
        p.rows[t]["close"] = 1.0
        p.decision(t, 1.0, False)
    assert p.records[0] == snapshot


def test_real_engine_fallback_next_open_funding_costs_caps_and_72_hours():
    p, times, entry = policy(n=300)
    index = pd.date_range(p.left, periods=301, freq="15min")
    bars = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0}, index=index
    )
    decisions = pd.DataFrame(
        {"le": False, "se": False, "lx": False, "sx": False, "distance": 4.0}, index=index
    )
    funding_time = times[5] + pd.Timedelta(milliseconds=47)
    funding = pd.DataFrame({"rate": [0.001]}, index=pd.DatetimeIndex([funding_time]))
    costs = CostsConfig(trading_fee_pct=0.05, slippage_pct=0.02, spread_pct=0.01)
    # Match the reference fee-adjusted fill so equal current quotes do not optimize.
    adjusted = replace(entry, baseline_entry_price=100.025)
    p = OptionalFillPolicy(
        pd.DataFrame.from_dict(p.rows, orient="index"),
        [adjusted],
        p.left,
        p.right,
        "ema_adx",
        costs,
    )
    result, _, events = execute(
        bars,
        bars,
        funding,
        decisions,
        p.left,
        p.right,
        costs,
        RiskConfig(risk_per_trade_pct=0.5, take_profit_enabled=False, max_holding_bars=72),
        timeframe="15m",
        direction="long",
        execution_policy=p,
    )
    (trade,) = result.trades
    assert trade.entry_time == times[4]
    assert trade.exit_time - trade.entry_time == pd.Timedelta(hours=72)
    assert trade.quantity * trade.entry_price + trade.entry_fee <= 2500 + 1e-6
    assert trade.expected_stop_loss <= trade.risk_budget <= 50
    assert trade.entry_fee == pytest.approx(trade.quantity * trade.entry_price * 0.0005)
    assert trade.funding_pnl == pytest.approx(-trade.quantity * 100 * 0.001)
    assert events[0]["time"] == funding_time
    assert result.equity.iloc[-1] == pytest.approx(10000 + trade.net_pnl)
    assert p.records[0]["fallback_used"]


def test_optimized_run_mapping_and_no_mutation_with_synthetic_origin():
    case = ("ETHUSDT", "ema_adx", "V2")
    data = dataset(candles(800))
    prepared = prepare_case(data, case)
    start, end = data["quarter"].index[0], data["quarter"].index[-1] + pd.Timedelta(minutes=15)
    costs = CostsConfig(trading_fee_pct=0.0, slippage_pct=0.0, spread_pct=0.0)
    before = baseline_run(prepared, start, end, costs, False)
    time = start + pd.Timedelta(hours=50)
    entry = BaselineEntry("b", "s", time, time, 1.0, 2.0, 4.0, 1.0, 1.0)
    result, _, _, records = optimized_run(prepared, case, [entry], start, end, costs, False)
    assert len(result.trades) == 1 and len(records) == 1
    assert records[0]["fallback_used"] and records[0]["baseline_trade_id"] == "b"
    after = baseline_run(prepared, start, end, costs, False)
    pd.testing.assert_series_equal(before[0].equity, after[0].equity)
    assert [asdict(t) for t in before[0].trades] == [asdict(t) for t in after[0].trades]


def test_config_rejects_retroactive_fallback_and_other_cases():
    protocol = load_protocol(Path.cwd())
    for changes in (
        {"fallback_mode": "retroactive_baseline"},
        {"window_minutes": 30},
        {"configurations": []},
    ):
        with pytest.raises(ValidationError):
            type(protocol).model_validate(protocol.model_dump() | changes)


def values():
    return {
        "return_pct": 20.0,
        "max_drawdown_pct": 10.0,
        "profit_factor": 1.4,
        "expectancy": 2.0,
        "total_costs": 500.0,
        "trade_retention_rate": 1.0,
        "number_of_worse_fills": 0,
        "number_of_worse_optimized_fills": 0,
        "average_fill_improvement_pct": 0.1,
    }


def test_classification_keeps_worse_fallback_losses_visible():
    b = values()
    assert classify(b, b, b, b, b, b, 12, 12)["classification"] == "FILL_IMPROVED"
    neutral = b | {"number_of_worse_fills": 1}
    assert classify(b, neutral, b, b, b, b, 12, 12)["classification"] == "FILL_NEUTRAL"
    for changes in (
        {"trade_retention_rate": 0.94},
        {"number_of_worse_optimized_fills": 1},
        {"expectancy": 1.8},
        {"profit_factor": 1.2},
        {"return_pct": 17.0},
    ):
        assert classify(b, b | changes, b, b, b, b, 12, 12)["classification"] == "FILL_WORSE"
    assert (
        classify(b, b | {"expectancy": None}, b, b, b, b, 12, 12)["classification"]
        == "FILL_NEUTRAL"
    )
    assert (
        classify(b, b, b, b, b, b | {"return_pct": 14.0}, 12, 12)["classification"] == "FILL_WORSE"
    )
