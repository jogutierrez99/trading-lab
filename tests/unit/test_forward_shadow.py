"""Causal shadow accounting, independent alternatives and deterministic reconstruction."""

from decimal import Decimal

import pandas as pd
import pytest

from quant_lab.brokers.instruments import Instrument
from quant_lab.config import CostsConfig
from quant_lab.forward.shadow import ShadowTracker, monetary_pnl
from quant_lab.forward.shadow_reporting import comparison, render
from quant_lab.market_data.okx import Bar
from quant_lab.risk import CostModel

T = pd.Timestamp("2026-01-01", tz="UTC")
INSTRUMENT = Instrument(
    "ETH", "ETH", Decimal("0.1"), Decimal("1"), Decimal("1"), Decimal("0.01"), Decimal("10")
)


def fixture(side="buy", policy="BASELINE", hours=72, costs=None, stamp=T, key="intent"):
    costs = costs or CostsConfig(trading_fee_pct=0.05, slippage_pct=0.02, spread_pct=0.01)
    model = CostModel.from_config(costs)
    intent = dict(
        id=key,
        timestamp=stamp.isoformat(),
        strategy=policy,
        asset="ETH",
        instrument_id="ETH",
        side=side,
        contracts="2",
        target_quantity=0.2,
        reference_price=100.0,
        estimated_entry_price=model.price(100, 1 if side == "buy" else -1),
        stop_price=90 if side == "buy" else 110,
        risk_budget=5,
        execution_policy=policy,
    )
    events = []
    tracker = ShadowTracker(costs, hours, lambda *args: events.append(args))
    p = tracker.open(intent, INSTRUMENT, "session", "signal", T)
    return tracker, p, intent, events


def bar(stamp=T, opening=100, high=105, low=95, close=102, tf="1h"):
    return Bar("ETH", tf, stamp, opening, high, low, close, 10)


@pytest.mark.parametrize(
    "side,close,sign", [("buy", 105, 1), ("buy", 95, -1), ("sell", 95, 1), ("sell", 105, -1)]
)
def test_direction_pnl_and_cost_attribution(side, close, sign):
    tracker, p, _, events = fixture(side, hours=1)
    tracker.update(bar(high=106, low=94, close=close))
    assert p["status"] == "CLOSED" and p["exit_reason"] == "MAX_HOLDING"
    assert p["realized_pnl_net"] * sign > 0
    assert p["reference_pnl_gross"] - p["total_cost"] == pytest.approx(p["realized_pnl_net"])
    assert p["realized_pnl_gross"] - p["entry_fee"] - p["exit_fee"] == pytest.approx(
        p["realized_pnl_net"]
    )
    assert events[-1][0] == "SHADOW_POSITION_CLOSED"
    tracker.update(bar())
    assert len(events) == 2


@pytest.mark.parametrize(
    "side,opening,high,low,expected",
    [
        ("buy", 100, 105, 89, 90),
        ("sell", 100, 111, 95, 110),
        ("buy", 85, 95, 80, 85),
        ("sell", 115, 120, 105, 115),
    ],
)
def test_stop_and_gap_no_post_stop_extremes(side, opening, high, low, expected):
    tracker, p, _, _ = fixture(side)
    tracker.update(bar(opening=opening, high=high, low=low, close=opening))
    assert p["exit_reason"] == "STOP"
    assert p["exit_reference_price"] == expected
    assert p["mfe_pnl"] <= abs(p["entry_price"] - opening) * p["quantity"]
    assert p["excursion_quality"] == "LOWER_BOUND_STOP_BAR"


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_excursions_and_mark(side):
    tracker, p, _, _ = fixture(side)
    tracker.update(bar())
    assert p["status"] == "OPEN" and p["bars_held"] == 1
    assert p["mfe_pnl"] == pytest.approx(
        monetary_pnl(p["side"], p["entry_price"], 105 if side == "buy" else 95, 0.2)
    )
    assert p["mae_pnl"] == pytest.approx(
        monetary_pnl(p["side"], p["entry_price"], 95 if side == "buy" else 105, 0.2)
    )
    assert p["mfe_r_multiple"] == pytest.approx(p["mfe_pnl"] / p["initial_risk"])
    assert p["unrealized_pnl_net_estimate"] < p["unrealized_pnl_gross"]


def test_gap_recovery_idempotence_and_no_warmup():
    tracker, p, intent, events = fixture()
    tracker.update(bar(T - pd.Timedelta(hours=1)))
    tracker.update(bar(), continuity_verified=False)
    assert p["bars_held"] == 0
    tracker.update(bar(T + pd.Timedelta(hours=1)))
    assert p["coverage"] == "DATA_GAP" and p["bars_held"] == 0
    tracker.update(bar())
    tracker.update(bar(T + pd.Timedelta(hours=1)))
    tracker.update(bar(T + pd.Timedelta(hours=1)))
    assert p["coverage"] == "CONTINUOUS" and p["bars_held"] == 2
    assert tracker.open(intent, INSTRUMENT, "session", "signal", T) is p
    assert len(events) == 1


def test_partial_entry_bar_does_not_use_pre_entry_extremes():
    tracker, p, _, _ = fixture(stamp=T + pd.Timedelta(seconds=1))
    tracker.update(bar(high=108, low=91, close=102))
    assert p["bars_held"] == 0 and p["mfe_price"] == 102
    assert p["mae_pnl"] == 0
    tracker, p, _, _ = fixture(stamp=T + pd.Timedelta(seconds=1))
    tracker.update(bar(low=89))
    assert p["coverage"] == "INDETERMINATE_ENTRY_BAR"
    assert p["exit_price"] is None and p["unrealized_pnl_net_estimate"] is None


def test_alternatives_pairing_closed_only_and_reports(tmp_path):
    tracker, p, intent, _ = fixture(hours=1)
    second = intent | dict(id="optional", strategy="optional", execution_policy="OPTIONAL_15M_FILL")
    other = tracker.open(second, INSTRUMENT, "session", "signal", T)
    tracker.update(bar())
    assert p["status"] == "CLOSED" and other["status"] == "OPEN"
    assert comparison(list(tracker.positions.values()))[0]["pnl_difference"] is None
    for i in range(4):
        tracker.update(bar(T + pd.Timedelta(minutes=15 * i), tf="15m"))
    assert other["bars_held"] == 4 and other["status"] == "CLOSED"
    assert comparison(list(tracker.positions.values()))[0]["pnl_difference"] == pytest.approx(0)
    summary = render(tmp_path, tracker.positions)
    assert "not a combined portfolio" in summary
    assert len(pd.read_csv(tmp_path / "shadow_trades.csv")) == 2


def test_contract_quantity_validation():
    tracker, _, intent, _ = fixture()
    with pytest.raises(ValueError, match="quantity mismatch"):
        tracker.open(intent | dict(id="bad", target_quantity=2), INSTRUMENT, "session", "signal", T)
