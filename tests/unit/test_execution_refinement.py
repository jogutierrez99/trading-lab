"""Execution-policy regressions independent of historical performance."""

from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd
import pytest

from quant_lab.config import CostsConfig, RiskConfig
from quant_lab.mtf_clock import execute
from quant_lab.mtf_features import complete_bars
from quant_lab.refinement_execution import prepare_case, run_case
from quant_lab.refinement_policy import ExecutionPolicy, Guards, diagnostics
from quant_lab.refinement_reporting import paper_gate


def policy(version="V4.1", n=10, config=None):
    times = pd.date_range("2020-01-02", periods=n, freq="15min", tz="UTC")
    frame = pd.DataFrame(
        {
            "new_signal": False,
            "origin_price": 100.0,
            "origin_reference": 99.0,
            "origin_atr": 2.0,
            "regime_valid": True,
            "setup_valid": True,
            "execution_trigger": False,
            "touch_open": times[0],
        },
        index=times,
    )
    frame.loc[times[0], "new_signal"] = True
    return ExecutionPolicy(
        frame,
        times[0] - pd.Timedelta(minutes=15),
        times[-1] + pd.Timedelta(minutes=15),
        "BTCUSDT",
        "bollinger",
        version,
        config,
    ), times


def test_freeze_wait_then_one_fill_and_no_duplicate():
    p, t = policy()
    assert p.decision(t[0], 100, False) is None
    original = p.active
    with pytest.raises(FrozenInstanceError):
        original.signal_price = 999
    p.features[t[2]].update(execution_trigger=True, origin_price=999, origin_reference=888)
    assert p.decision(t[2], 101, False)["distance"] == 4
    assert p.active == original
    p.on_entry(t[2], 101)
    p.features[t[3]]["execution_trigger"] = True
    assert p.decision(t[3], 101, False) is None
    stats, records, _ = diagnostics([p])
    assert stats["signals_consumed"] == 1 and stats["duplicate_entries_prevented"] == 1
    assert records[0]["signal_price"] == 100 and records[0]["time_to_entry"] == 0.5


def test_expiry_and_fourth_close_boundary():
    p, t = policy()
    p.decision(t[0], 100, False)
    for time in t[1:5]:
        assert p.decision(time, 100, False) is None
    assert diagnostics([p])[0]["signals_expired"] == 1
    p, t = policy()
    p.decision(t[0], 100, False)
    p.features[t[4]]["execution_trigger"] = True
    assert p.decision(t[4], 100, False) is not None
    p.on_entry(t[4], 100)
    assert diagnostics([p])[1][0]["signal_age"] == 1


@pytest.mark.parametrize(
    "field,reason", [("regime_valid", "regime_changed"), ("setup_valid", "setup_invalid")]
)
def test_invalidation(field, reason):
    p, t = policy()
    p.decision(t[0], 100, False)
    p.features[t[1]][field] = False
    p.decision(t[1], 100, False)
    assert diagnostics([p])[1][0]["expiry_reason"] == reason


def test_extension_is_at_open_and_cancels_even_without_trigger():
    p, t = policy()
    p.decision(t[0], 100, False)
    assert p.decision(t[1], 103.01, False) is None
    stats, records, _ = diagnostics([p])
    assert stats["extension_entries_blocked"] == 1 and records[0]["invalidated"]
    p, t = policy("V2.1")
    assert p.decision(t[0], 103, False) is not None


def test_position_gate_cooldown_and_distinct_hourly_ids():
    p, t = policy("V2.1")
    p.features[t[4]]["new_signal"] = True
    p.features[t[8]]["new_signal"] = True
    assert p.decision(t[0], 100, False) is not None
    p.on_entry(t[0], 100)
    p.on_exit(t[2])
    assert p.decision(t[4], 100, False) is None
    assert p.decision(t[8], 100, False) is not None
    p.on_entry(t[8], 100)
    stats, records, _ = diagnostics([p])
    assert stats["cooldown_entries_blocked"] == 1 and stats["signals_consumed"] == 2
    assert len({r["signal_id"] for r in records}) == 3
    p, t = policy("V2.1")
    assert p.decision(t[0], 100, True) is None
    assert diagnostics([p])[0]["duplicate_entries_prevented"] == 1


def test_no_retry_of_failed_hourly_execution():
    p, t = policy("V2.1")
    assert p.decision(t[0], 100, False) is not None
    # No fill callback: a rejected size must not become a delayed hourly trade.
    assert p.decision(t[1], 100, False) is None
    assert diagnostics([p])[0]["signals_invalidated"] == 1


def test_gap_finalization_and_deterministic_ids():
    p, t = policy()
    q, _ = policy()
    p.decision(t[0], 100, False)
    q.decision(t[0], 100, False)
    assert p.active.signal_id == q.active.signal_id
    p.finalize(t[1], "gap_or_segment_end")
    assert p.active is None
    assert diagnostics([p])[1][0]["expiry_reason"] == "gap_or_segment_end"


def test_spread_guard_requires_real_data_and_is_disabled_by_default():
    p, t = policy("V2.1")
    assert not p.config.dynamic_spread_enabled
    with pytest.raises(ValueError, match="observed"):
        policy(config=Guards(dynamic_spread_enabled=True, max_spread_pct=0.1))
    p, t = policy("V2.1")
    p.config = Guards(dynamic_spread_enabled=True, max_spread_pct=0.1)
    p.spreads = {t[0]: 0.2}
    assert p.decision(t[0], 100, False) is None
    assert diagnostics([p])[1][0]["expiry_reason"] == "spread_unavailable_or_high"


def dataset(n=4000):
    index = pd.date_range("2020-01-01", periods=n, freq="15min", tz="UTC")
    x = np.arange(n)
    close = 100 + x * 0.005 + np.sin(x / 10) * 2
    q = pd.DataFrame(
        {"open": close, "high": close + 0.5, "low": close - 0.5, "close": close, "volume": 1.0},
        index=index,
    )
    h = complete_bars(q, "15m", "1h")
    return {
        "frames": {"1h": h},
        "mark": h,
        "quarter": q,
        "quarter_mark": q,
        "funding": pd.DataFrame({"rate": []}, index=pd.DatetimeIndex([], tz="UTC")),
    }


@pytest.mark.parametrize(
    "family,version", [("donchian", "V2"), ("ema_adx", "V2"), ("bollinger", "V4")]
)
def test_prefix_features_4h_1h_15m_and_hourly_origins(family, version):
    data = dataset()
    full = prepare_case(data, "BTCUSDT", family, version)[2][0][-1]
    prefix = dataset(3600)
    part = prepare_case(prefix, "BTCUSDT", family, version)[2][0][-1]
    pd.testing.assert_frame_equal(part, full.loc[part.index])
    assert (full.index[full.new_signal].minute == 0).all()
    if version == "V4":
        assert full.loc[full.index.minute != 0, "new_signal"].eq(False).all()


def test_gap_resets_warmup():
    data = dataset()
    excluded = data["frames"]["1h"].index[850:874]
    data["frames"]["1h"] = data["frames"]["1h"].drop(excluded)
    for k in ("mark", "quarter", "quarter_mark"):
        data[k] = data[k].loc[~data[k].index.floor("h").isin(excluded)]
    blocks = prepare_case(data, "BTCUSDT", "bollinger", "V4")[2]
    assert len(blocks) == 2
    last = blocks[-1][-1]
    assert last.origin_atr.iloc[:50].isna().all()
    # Bollinger regime needs 20 closed 4h bars (80h) after the new segment.
    assert not last.new_signal.iloc[: 79 * 4].any()


def test_hooks_funding_costs_intrabar_cooldown_and_repeatability():
    p, t = policy("V2.1", n=10)
    idx = pd.date_range(t[0] - pd.Timedelta(minutes=15), periods=11, freq="15min")
    f = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0}, index=idx
    )
    f.loc[t[2], "low"] = 90.0
    fund = pd.DataFrame(
        {"rate": [0.001]}, index=pd.DatetimeIndex([t[1] + pd.Timedelta(milliseconds=47)])
    )
    d = pd.DataFrame(
        columns=["le", "se", "lx", "sx", "distance"], index=pd.DatetimeIndex([], tz="UTC")
    )

    def go():
        policy_, _ = policy("V2.1", n=10)
        policy_.features[t[4]]["new_signal"] = True
        output = execute(
            f,
            f,
            fund,
            d,
            idx[0],
            idx[-1] + pd.Timedelta(minutes=15),
            CostsConfig(trading_fee_pct=0.05, slippage_pct=0.02, spread_pct=0.01),
            RiskConfig(max_holding_bars=72, take_profit_enabled=False),
            timeframe="15m",
            execution_policy=policy_,
        )
        return output, policy_

    (r, s, events), p = go()
    (again, s2, e2), p2 = go()
    assert r.trades == again.trades and events == e2
    pd.testing.assert_series_equal(r.equity, again.equity)
    assert p.events == p2.events
    (trade,) = r.trades
    assert trade.funding_pnl == pytest.approx(-trade.quantity * 100 * 0.001)
    assert trade.entry_fee == pytest.approx(trade.entry_price * trade.quantity * 0.0005)
    assert p.last_exit == t[3]
    assert diagnostics([p])[0]["cooldown_entries_blocked"] == 1
    assert events[0]["time"] == fund.index[0]
    assert r.equity.iloc[-1] == pytest.approx(10000 + trade.net_pnl)


def test_no_paper_label_can_override_low_sample_or_cost_failure():
    row = dict(
        expectancy=1.0,
        profit_factor=1.2,
        sharpe=0.5,
        adverse_return=1.0,
        validation=1.0,
        test=1.0,
        final_holdout=1.0,
        wf_positive_fold_ratio=0.6,
        closed_trades=100,
        max_drawdown_pct=5.0,
        zero_return=3.0,
        return_pct=2.0,
    )
    hold = dict(closed_trades=30, return_pct=1.0, expectancy=1.0, max_drawdown_pct=2.0)
    assert paper_gate(row, row, hold, hold)["operational_label"] == "PAPER_TRADING_CANDIDATE"
    assert (
        "sample_below_existing_minimum"
        in paper_gate(row, row, hold | {"closed_trades": 29}, hold)["failed_operational_gates"]
    )
    assert (
        "adverse_cost_edge"
        in paper_gate(row | {"adverse_return": 0}, row, hold, hold)["failed_operational_gates"]
    )


def test_window_execution_has_complete_lifecycle_and_no_hidden_entries():
    data = dataset()
    prepared = prepare_case(data, "BTCUSDT", "bollinger", "V4")
    start = data["quarter"].index[0]
    end = data["quarter"].index[-1] + pd.Timedelta(minutes=15)
    a = run_case(prepared, "BTCUSDT", "bollinger", "V4.1", start, end, CostsConfig())
    b = run_case(prepared, "BTCUSDT", "bollinger", "V4.1", start, end, CostsConfig())
    assert a[0].trades == b[0].trades
    assert a[4] == b[4] and a[5] == b[5]
    stats = a[3]
    assert (
        stats["signals_generated"]
        == stats["signals_consumed"] + stats["signals_expired"] + stats["signals_invalidated"]
    )
