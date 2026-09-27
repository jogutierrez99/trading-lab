"""Synthetic accounting regressions, independent of historical outcomes."""

from dataclasses import replace

import pandas as pd
import pytest

from quant_lab.batch_006_analysis import excursions, metrics
from quant_lab.batch_006_execution import execute_window, walk_forward_windows
from quant_lab.config import CostsConfig, RiskConfig
from quant_lab.futures_data import funding_frame, validate_funding
from quant_lab.perpetual_execution import run_perpetual
from quant_lab.study_plan import windows


def test_holdout_unlock_rejects_missing_failed_or_future_runs(tmp_path):
    from quant_lab.batch_006 import unlock_holdout
    from quant_lab.experiments import ExperimentStore

    boundary = pd.Timestamp("2025-01-01", tz="UTC")
    store = ExperimentStore(tmp_path, {}, {})
    with pytest.raises(ValueError, match="locked"):
        unlock_holdout(store, 1, boundary, "test")
    id_ = store.start({"end": str(boundary)})
    with pytest.raises(ValueError, match="locked"):
        unlock_holdout(store, 1, boundary, "test")
    store.finish(id_, {})
    unlock_holdout(store, 1, boundary, "test")
    assert (store.path / "holdout_unlock.json").exists()
    future = ExperimentStore(tmp_path, {}, {})
    id_ = future.start({"end": str(boundary + pd.Timedelta(days=1))})
    future.finish(id_, {})
    with pytest.raises(ValueError, match="locked"):
        unlock_holdout(future, 1, boundary, "test")


def test_signal_edge_includes_entries_ignored_by_position_and_censors_gap():
    from quant_lab.batch_006_analysis import signal_follow_through

    f, d, fund = market(8)
    d.loc[f.index[1:4], "se"] = True
    f.loc[:, "close"] = 95.0
    output = signal_follow_through(
        [(f, f, fund, d, pd.DataFrame())], f.index[0], f.index[-1] + pd.Timedelta(hours=1), "4h"
    )
    assert output["summary"]["short"]["1_bars"]["n"] == 3
    assert output["summary"]["short"]["1_bars"]["mean"] == pytest.approx(5.0)
    assert output["summary"]["short"]["3_bars"]["censored"] == 3
    assert "6_hours" not in output["summary"]["short"]


def market(n=5):
    index = pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0}, index=index
    )
    decisions = pd.DataFrame(
        {"le": False, "se": False, "lx": False, "sx": False, "distance": 10.0}, index=index
    )
    funding = pd.DataFrame({"rate": pd.Series(dtype=float)}, index=pd.DatetimeIndex([], tz="UTC"))
    return frame, decisions, funding


def simulate(frame, decisions, funding, side="long", costs=None, risk=None, mark=None):
    return run_perpetual(
        frame,
        frame if mark is None else mark,
        funding,
        decisions,
        frame.index[0],
        frame.index[-1] + pd.Timedelta(hours=1),
        costs or CostsConfig(trading_fee_pct=0, slippage_pct=0, spread_pct=0),
        risk or RiskConfig(risk_per_trade_pct=0.5, take_profit_enabled=False),
        direction=side,
    )


@pytest.mark.parametrize("side,sign", [("long", 1), ("short", -1)])
def test_direction_pnl_costs_funding_and_reconciliation(side, sign):
    f, d, fund = market()
    d.loc[f.index[1], "le" if sign == 1 else "se"] = True
    d.loc[f.index[3], "lx" if sign == 1 else "sx"] = True
    f.loc[f.index[3], ["open", "high", "low", "close"]] = [100 + sign * 5, 106, 94, 100 + sign * 5]
    fund = pd.DataFrame({"rate": [0.001]}, index=f.index[2:3])
    costs = CostsConfig(trading_fee_pct=0.05, slippage_pct=0.02, spread_pct=0.01)
    result, sides, events = simulate(f, d, fund, side, costs)
    (t,) = result.trades
    assert t.side == side
    assert t.entry_time == f.index[1] and t.exit_time == f.index[3]
    assert t.net_pnl > 0
    assert t.funding_pnl == pytest.approx(-sign * t.quantity * 100 * 0.001)
    assert t.entry_fee == pytest.approx(t.entry_price * t.quantity * 0.0005)
    assert t.exit_fee == pytest.approx(t.exit_price * t.quantity * 0.0005)
    assert t.expected_stop_loss <= 50
    assert t.initial_margin + t.entry_fee <= 2500
    assert len(events) == 1
    q, _ = excursions(f, result, "1h")
    m = metrics(result, sides, q)
    assert m["realized_net_pnl"] == pytest.approx(t.net_pnl)
    assert result.equity.iloc[-1] == pytest.approx(10000 + t.net_pnl)


@pytest.mark.parametrize("side", ["long", "short"])
@pytest.mark.parametrize("target", [False, True])
def test_stops_and_targets_on_both_directions(side, target):
    f, d, fund = market()
    d.loc[f.index[1], "le" if side == "long" else "se"] = True
    up = (side == "short") != target
    f.loc[f.index[2], "high" if up else "low"] = 125 if up else 75
    result, _, _ = simulate(
        f, d, fund, side, risk=RiskConfig(take_profit_enabled=target, risk_reward=2)
    )
    (t,) = result.trades
    assert t.reason == ("target" if target else "stop")
    assert (t.net_pnl > 0) == target
    assert t.exit_price == pytest.approx(100 + (20 if target else 10) * (1 if up else -1))


def test_no_reversal_no_pyramiding_and_direction_gate():
    f, d, fund = market(7)
    d.loc[f.index[1:4], "le"] = True
    d.loc[f.index[2:5], "se"] = True
    d.loc[f.index[3], "lx"] = True
    d.loc[f.index[5], "sx"] = True
    result, sides, _ = simulate(f, d, fund, "combined")
    assert [t.side for t in result.trades] == ["long", "short"]
    assert [t.entry_time for t in result.trades] == [f.index[1], f.index[4]]
    assert set(sides) == {-1, 0, 1}
    for side in ("long", "short"):
        result, _, _ = simulate(f, d, fund, side)
        assert all(t.side == side for t in result.trades)


@pytest.mark.parametrize("delay_ms,expected_count", [(0, 0), (1, 1), (47, 1)])
def test_new_entry_funding_exact_boundary_vs_observed_delay(delay_ms, expected_count):
    f, d, _ = market()
    d.loc[f.index[1], "le"] = True
    fund = pd.DataFrame(
        {"rate": [0.001]},
        index=pd.DatetimeIndex([f.index[1] + pd.Timedelta(milliseconds=delay_ms)]),
    )
    result, _, events = simulate(f, d, fund)
    assert result.trades[0].funding_events == expected_count
    assert len(events) == expected_count
    if events:
        assert events[0]["time"] == fund.index[0]


@pytest.mark.parametrize("delay_ms,expected_count", [(0, 1), (1, 0)])
def test_exit_funding_boundary_order(delay_ms, expected_count):
    f, d, _ = market()
    d.loc[f.index[1], "se"] = True
    d.loc[f.index[2], "sx"] = True
    fund = pd.DataFrame(
        {"rate": [0.001]},
        index=pd.DatetimeIndex([f.index[2] + pd.Timedelta(milliseconds=delay_ms)]),
    )
    result, _, _ = simulate(f, d, fund, "short")
    assert result.trades[0].funding_events == expected_count


def test_liquidation_precedes_ambiguous_stop_and_caps_isolated_loss():
    f, d, fund = market()
    d.loc[f.index[1], "se"] = True
    f.loc[f.index[2], "high"] = 250.0
    result, sides, _ = simulate(f, d, fund, "short")
    (t,) = result.trades
    assert t.reason == "liquidation_intrabar"
    assert t.liquidation_fee > 0 and t.bankruptcy_adjustment > 0
    assert t.net_pnl == pytest.approx(-t.initial_margin)
    assert result.equity.iloc[-1] >= 7500
    q, _ = excursions(f, result, "1h")
    assert metrics(result, sides, q)["liquidations"] == 1


def test_short_excursion_and_follow_through_use_linear_return():
    f, d, fund = market()
    d.loc[f.index[1], "se"] = True
    f.loc[f.index[1:3], "low"] = 95.0
    f.loc[f.index[1:3], "high"] = 102.0
    f.loc[f.index[1:3], "close"] = 96.0
    d.loc[f.index[3], "sx"] = True
    result, _, _ = simulate(f, d, fund, "short")
    q, e = excursions(f, result, "1h")
    assert q["summary"]["short"]["mfe_pct_mean"] == pytest.approx(5)
    assert q["summary"]["short"]["mae_pct_mean"] == pytest.approx(2)
    assert e["summary"]["short"]["1_bars"]["mean"] == pytest.approx(4)
    assert e["summary"]["short"]["24_bars"]["n"] == 0
    assert e["summary"]["short"]["24_bars"]["censored"] == 1
    short = replace(
        result.trades[0], exit_timing="open", exit_bar_open=f.index[2], exit_time=f.index[2]
    )
    f.loc[f.index[2], "low"] = 1
    q, _ = excursions(f, replace(result, trades=(short,)), "1h")
    assert q["summary"]["short"]["mfe_pct_mean"] == pytest.approx(5)


def test_time_stop_and_partition_boundary_isolation():
    f, d, fund = market(80)
    d.loc[f.index[0:2], "le"] = True
    result, _, _ = simulate(
        f, d, fund, risk=RiskConfig(max_holding_bars=72, take_profit_enabled=False)
    )
    (t,) = result.trades
    assert t.entry_time == f.index[1]
    assert t.exit_time == f.index[73] and t.reason == "time_stop"
    labels = pd.DataFrame({"trend": "SIDEWAYS"}, index=f.index)
    block = (f, f, fund, d, labels)
    costs = CostsConfig(trading_fee_pct=0, slippage_pct=0, spread_pct=0)
    first = execute_window([block], "4h", "A", "LONG_SHORT", f.index[0], f.index[50], costs)[0]
    changed = f.copy()
    changed.loc[f.index[50] :, "close"] = 200
    second = execute_window(
        [(changed, changed, fund, d, labels)],
        "4h",
        "A",
        "LONG_SHORT",
        f.index[0],
        f.index[50],
        costs,
    )[0]
    assert first.trades == second.trades
    pd.testing.assert_series_equal(first.equity, second.equity)


def test_calendar_splits_and_no_overlapping_wf_test():
    start, end = pd.Timestamp("2020-01-01", tz="UTC"), pd.Timestamp("2026-09-22", tz="UTC")
    parts = windows(start, end)
    assert parts[0][1] == start and parts[-1][2] == end
    assert all(a[2] == b[1] for a, b in zip(parts, parts[1:], strict=False))
    folds = walk_forward_windows(start, end)
    assert len(folds) == 22
    for a, b, c in folds:
        assert a + pd.DateOffset(months=12) == b
        assert b + pd.DateOffset(months=3) == c <= end
    assert all(a[2] == b[1] for a, b in zip(folds, folds[1:], strict=False))


def test_funding_parser_retains_observed_rates_offsets_and_rejects_corruption():
    payload = b"calc_time,funding_interval_hours,last_funding_rate\n1577836800047,8,-0.00012359\n"
    frame = funding_frame(payload)
    assert frame.rate.iloc[0] == -0.00012359
    assert frame.index[0].microsecond == 47000
    with pytest.raises(ValueError, match="timestamps"):
        validate_funding(pd.concat([frame, frame]))
    frame.loc[:, "rate"] = float("nan")
    with pytest.raises(ValueError, match="values"):
        validate_funding(frame)
