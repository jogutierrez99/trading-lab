import pandas as pd
import pytest

from quant_lab.backtest import ReferenceBackend
from quant_lab.config import AppConfig, CostsConfig, RiskConfig
from quant_lab.execution_config import ExecutionConfig
from quant_lab.history import HistoryRequest
from quant_lab.metrics import summarize
from quant_lab.strategies.base import Signals


def run(
    rows,
    entries=(0,),
    exits=(),
    shorts=(),
    short_exits=(),
    distance=10.0,
    warmup=0,
    execution=None,
    costs=None,
    risk=None,
    distances=None,
    fractions=None,
):
    index = pd.date_range("2022-01-01", periods=len(rows), freq="h", tz="UTC", name="open_time")
    frame = pd.DataFrame(rows, index=index, columns=["open", "high", "low", "close"])
    frame["volume"] = 100.0
    history = HistoryRequest(
        start=index[warmup].to_pydatetime(),
        end=(index[-1] + pd.Timedelta(hours=1)).to_pydatetime(),
        warmup_bars=warmup,
    )
    signals = Signals(
        *(
            tuple(i in indexes for i in range(len(rows)))
            for indexes in (entries, exits, shorts, short_exits)
        )
    )
    return ReferenceBackend().run(
        frame,
        signals,
        pd.Series(distances if distances is not None else distance, index=index),
        history,
        AppConfig(
            costs=costs or CostsConfig(trading_fee_pct=0.0, slippage_pct=0.0, spread_pct=0.0)
        ),
        risk or RiskConfig(risk_per_trade_pct=0.5, max_position_pct=100.0),
        execution
        or ExecutionConfig(
            quantity_step=0.001, min_quantity=0.0, min_notional=0.0, filter_assumption="test"
        ),
        entry_fractions=pd.Series(fractions, index=index) if fractions is not None else None,
    )


FLAT = [100.0, 101.0, 99.0, 100.0]


def test_next_open_and_last_signal_not_filled():
    result = run([FLAT, [110.0, 111.0, 109.0, 110.0], [115.0, 116.0, 114.0, 115.0]], entries=(0, 2))
    (trade,) = result.trades
    assert trade.entry_price == 110.0
    assert trade.entry_time == pd.Timestamp("2022-01-01T01:00Z")
    assert trade.signal_close == trade.entry_time
    assert trade.reason == "end_of_study"
    assert trade.net_pnl == 25.0
    assert trade.quantity == 5.0
    assert len(result.equity) == 4


def test_warmup_signals_are_not_orders():
    result = run([FLAT] * 4, warmup=2, entries=(0, 1, 2))
    assert len(result.trades) == 1
    assert result.trades[0].entry_time.hour == 3
    assert len(result.equity) == 3


@pytest.mark.parametrize(
    "row,reason,price",
    [
        ([100.0, 121.0, 89.0, 100.0], "stop", 90.0),
        ([100.0, 120.0, 99.0, 110.0], "target", 120.0),
        ([80.0, 85.0, 75.0, 80.0], "stop_gap", 80.0),
        ([125.0, 130.0, 85.0, 100.0], "target_gap", 120.0),
    ],
)
def test_long_protective_ordering(row, reason, price):
    result = run([FLAT, FLAT, row])
    (trade,) = result.trades
    assert trade.reason == reason
    assert trade.exit_price == price
    assert (trade.exit_time is None) == (reason in ("stop", "target"))
    assert trade.net_pnl == 5 * (price - 100)


def test_stop_is_active_on_entry_bar():
    (trade,) = run([FLAT, [100.0, 125.0, 85.0, 100.0]]).trades
    assert trade.reason == "stop"
    assert trade.entry_time == trade.exit_bar_open


def test_gap_precedes_pending_signal_exit():
    result = run([FLAT, FLAT, [80.0, 85.0, 75.0, 80.0]], exits=(1,))
    assert result.trades[0].reason == "stop_gap"


def test_signal_exit_precedes_later_intrabar_stop_and_no_reentry():
    result = run([FLAT, FLAT, [100.0, 125.0, 85.0, 100.0], FLAT], entries=(0, 1), exits=(1,))
    assert len(result.trades) == 1
    assert result.trades[0].reason == "signal"
    assert result.trades[0].exit_price == 100.0


def test_both_side_costs_and_net_equity_reconcile():
    costs = CostsConfig(trading_fee_pct=0.1, slippage_pct=0.03, spread_pct=0.02)
    result = run([FLAT] * 3, costs=costs)
    (trade,) = result.trades
    assert trade.entry_price == pytest.approx(100.04)
    assert trade.exit_price == pytest.approx(99.96)
    assert trade.entry_fee == pytest.approx(trade.quantity * 100.04 * 0.001)
    assert trade.exit_fee == pytest.approx(trade.quantity * 99.96 * 0.001)
    assert trade.net_pnl == pytest.approx(-trade.quantity * 0.08 - trade.entry_fee - trade.exit_fee)
    assert result.equity.iloc[-1] == pytest.approx(10000 + trade.net_pnl)
    assert trade.expected_stop_loss <= 50
    assert summarize(result)["fees_paid"] == pytest.approx(trade.entry_fee + trade.exit_fee)


def test_risk_stop_budget_with_costs_and_gap_overrun():
    costs = CostsConfig(trading_fee_pct=0.1, slippage_pct=0.03, spread_pct=0.02)
    stopped = run([FLAT, FLAT, [100.0, 100.0, 80.0, 95.0]], costs=costs).trades[0]
    assert -stopped.net_pnl == pytest.approx(stopped.expected_stop_loss)
    assert -stopped.net_pnl <= 50
    gap = run([FLAT, FLAT, [70.0, 75.0, 65.0, 70.0]], costs=costs).trades[0]
    assert -gap.net_pnl > gap.risk_budget


def test_capital_cap_and_rounding():
    risk = RiskConfig(risk_per_trade_pct=50.0, max_position_pct=20.0, max_exposure_pct=25.0)
    execution = ExecutionConfig(
        quantity_step=0.1, min_quantity=0.0, min_notional=0.0, filter_assumption="test"
    )
    trade = run(
        [FLAT] * 2,
        risk=risk,
        execution=execution,
        costs=CostsConfig(trading_fee_pct=1.0, slippage_pct=0.0, spread_pct=0.0),
    ).trades[0]
    assert trade.quantity == 19.8
    assert trade.quantity * trade.entry_price + trade.entry_fee <= 2000


@pytest.mark.parametrize("distance", [float("nan"), 0.0, -1.0, float("inf"), 200.0])
def test_invalid_stop_rejected(distance):
    result = run([FLAT] * 2, distance=distance)
    assert not result.trades
    assert len(result.rejections) == 1


def test_minimum_notional_rejected():
    config = ExecutionConfig(
        quantity_step=1.0, min_quantity=0.0, min_notional=1000.0, filter_assumption="test"
    )
    result = run([FLAT] * 2, execution=config)
    assert result.rejections[0].reason == "below_min_notional"


def synthetic(direction):
    return ExecutionConfig(
        market_mode="synthetic",
        direction=direction,
        quantity_step=0.001,
        min_quantity=0.0,
        min_notional=0.0,
        filter_assumption="test",
    )


@pytest.mark.parametrize(
    "row,reason,price",
    [
        ([100.0, 111.0, 79.0, 100.0], "stop", 110.0),
        ([100.0, 101.0, 80.0, 90.0], "target", 80.0),
        ([125.0, 130.0, 120.0, 125.0], "stop_gap", 125.0),
        ([75.0, 115.0, 70.0, 100.0], "target_gap", 80.0),
    ],
)
def test_synthetic_short_symmetry(row, reason, price):
    result = run([FLAT, FLAT, row], entries=(), shorts=(0,), execution=synthetic("short"))
    (trade,) = result.trades
    assert trade.side == "short"
    assert trade.reason == reason
    assert trade.exit_price == price
    assert trade.net_pnl == 5 * (100 - price)


def test_spot_rejects_short_configuration():
    with pytest.raises(ValueError, match="Spot"):
        ExecutionConfig(
            direction="short",
            quantity_step=1.0,
            min_quantity=0.0,
            min_notional=0.0,
            filter_assumption="test",
        )


def test_combined_conflicts_and_independent_accounts():
    rows = [FLAT] * 3
    combined = run(rows, shorts=(0,), execution=synthetic("combined"))
    assert not combined.trades
    assert combined.rejections[0].reason == "conflicting_entries"
    for direction in ("long", "short"):
        result = run(rows, shorts=(0,), execution=synthetic(direction))
        assert len(result.trades) == 1
        assert result.equity.iloc[0] == 10000


def test_signal_at_close_uses_previous_stop_distance():
    trade = run([FLAT, FLAT, [100.0, 105.0, 89.0, 100.0]], distances=[10.0, 50.0, 1.0]).trades[0]
    assert trade.stop == 90
    assert trade.reason == "stop"


def test_prefix_execution_without_terminal_liquidation():
    config = ExecutionConfig(
        quantity_step=0.001,
        min_quantity=0.0,
        min_notional=0.0,
        filter_assumption="test",
        liquidate_at_end=False,
    )
    short = run([FLAT] * 3, execution=config)
    longer = run([FLAT] * 5, execution=config)
    pd.testing.assert_series_equal(short.equity, longer.equity.iloc[: len(short.equity)])
    assert not short.trades and short.open_position is not None


def test_metrics_include_initial_capital_and_no_trade_case():
    empty = summarize(run([FLAT] * 2, entries=()))
    assert empty["return_pct"] == 0 and empty["max_drawdown_pct"] == 0
    assert empty["win_rate_pct"] is None
    stopped = summarize(run([FLAT, [100.0, 101.0, 89.0, 95.0]]))
    assert stopped["max_drawdown_pct"] == pytest.approx(0.5)
    assert stopped["return_pct"] == pytest.approx(-0.5)
    assert stopped["profit_factor"] == 0


def test_trailing_waits_until_next_bar_and_never_loosens():
    risk = RiskConfig(
        risk_per_trade_pct=0.5,
        max_position_pct=100.0,
        take_profit_enabled=False,
        atr_multiplier=2.0,
        trailing_atr_multiplier=2.0,
    )
    # Entry bar low=95 must NOT hit the new trailing=110 calculated at its close.
    result = run(
        [
            FLAT,
            [100.0, 120.0, 95.0, 115.0],
            [115.0, 116.0, 112.0, 114.0],
            [114.0, 115.0, 109.0, 110.0],
        ],
        risk=risk,
        distances=[10.0, 10.0, 30.0, 30.0],
    )
    trade = result.trades[0]
    assert trade.exit_bar_open.hour == 3
    assert trade.exit_price == 110
    assert trade.stop == 110


def test_short_trailing_and_next_open_gap():
    risk = RiskConfig(take_profit_enabled=False, trailing_atr_multiplier=2.0)
    result = run(
        [FLAT, [100.0, 105.0, 80.0, 85.0], [95.0, 100.0, 90.0, 95.0]],
        entries=(),
        shorts=(0,),
        execution=synthetic("short"),
        risk=risk,
    )
    assert result.trades[0].reason == "stop_gap"
    assert result.trades[0].exit_price == 95


def test_time_stop_counts_entry_bar_and_exits_next_open():
    risk = RiskConfig(take_profit_enabled=False, max_holding_bars=2)
    trade = run([FLAT] * 5, risk=risk).trades[0]
    assert trade.entry_time.hour == 1
    assert trade.exit_time.hour == 3
    assert trade.holding_bars == 2
    assert trade.reason == "time_stop"


def test_fixed_notional_no_stop_no_repeated_entries_and_costs():
    risk = RiskConfig(
        sizing_method="fixed_notional",
        position_pct=25.0,
        stop_enabled=False,
        take_profit_enabled=False,
    )
    result = run(
        [FLAT] * 4 + [[50.0, 51.0, 49.0, 50.0]],
        entries=(0, 1, 2, 3),
        risk=risk,
        distance=float("nan"),
    )
    (trade,) = result.trades
    assert trade.quantity == 25
    assert trade.stop is None and trade.target is None
    assert trade.risk_budget is None and trade.expected_stop_loss is None
    assert trade.net_pnl == -1250
    assert result.turnover == 3750


def test_daily_returns_midnight_and_zero_denominators():
    from quant_lab.metrics import daily_returns

    equity = pd.Series(
        [100.0, 110.0, 99.0], index=pd.date_range("2022-01-01", periods=3, freq="D", tz="UTC")
    )
    assert daily_returns(equity).tolist() == pytest.approx([0.1, -0.1])
    metrics = summarize(run([FLAT] * 3, entries=()))
    assert metrics["sharpe"] is None and metrics["sortino"] is None
    assert metrics["funding_pnl"] is None


def test_close_trailing_ignores_high_and_entry_open_until_first_close():
    risk = RiskConfig(
        take_profit_enabled=False, trailing_atr_multiplier=2.0, trailing_basis="close"
    )
    # High 130 must not yield stop 120; close 105 produces stop 95 at NEXT bar.
    trade = run([FLAT, [100.0, 130.0, 99.0, 105.0], [105.0, 106.0, 94.0, 95.0]], risk=risk).trades[
        0
    ]
    assert trade.reason == "stop" and trade.exit_price == 95
    assert trade.exit_bar_open.hour == 2
    # Entry open above first close must not be counted as a close extreme.
    trade = run([FLAT, [100.0, 101.0, 91.0, 95.0], [95.0, 96.0, 91.0, 92.0]], risk=risk).trades[0]
    assert trade.reason == "end_of_study" and trade.stop == 90


def test_volatility_sizing_uses_signal_fraction_and_does_not_rebalance():
    risk = RiskConfig(
        sizing_method="volatility_target", stop_enabled=False, take_profit_enabled=False
    )
    result = run([FLAT] * 4, entries=(0, 1, 2), risk=risk, fractions=[0.1, 0.25, 0.05, 0.25])
    assert len(result.trades) == 1
    assert result.trades[0].quantity == 10
    assert result.exposure.iloc[2] == 0.1
    assert result.trades[0].stop is None
    invalid = run([FLAT] * 3, risk=risk, fractions=[float("nan"), 0.25, 0.25])
    assert invalid.rejections[0].reason == "invalid_entry_fraction"
    assert len(invalid.equity) == 4  # Rejection must not drop an equity timestamp.
    with pytest.raises(ValueError, match="requires"):
        run([FLAT] * 3, risk=risk)
