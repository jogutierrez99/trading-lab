"""Reject altered evidence, unsafe preregistrations and invalid saved accounting."""

from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from quant_lab.eth_donchian_review import (
    POLICY,
    Protocol,
    audit_trade,
    checked_path,
    evidence_catalog,
    load_protocol,
    neighbors,
)

ROOT = Path(__file__).resolve().parents[2]
COSTS = dict(trading_fee_pct=0.05, slippage_pct=0.03, spread_pct=0.01)


def trade(quantity=20):
    fee, slip, spread = 0.0005, 0.0003, 0.00005
    entry, exit_price, stop = 100.0, 99.0, 101.0
    a, b = entry / (1 - slip - spread), exit_price / (1 + slip + spread)
    return dict(
        side="short",
        signal_close="2026-10-10T01:00:00Z",
        entry_time="2026-10-10T01:00:00Z",
        quantity=quantity,
        entry_price=entry,
        exit_price=exit_price,
        stop=stop,
        target=98.0,
        entry_reference=a,
        exit_reference=b,
        entry_fee=quantity * entry * fee,
        exit_fee=quantity * exit_price * fee,
        net_pnl=quantity * (entry - exit_price) - quantity * (entry + exit_price) * fee,
        slippage_cost=quantity * (a + b) * slip,
        spread_cost=quantity * (a + b) * spread,
        expected_stop_loss=quantity
        * (stop * (1 + slip + spread) - entry + fee * (entry + stop * (1 + slip + spread))),
        risk_budget=100.0,
    )


def test_valid_saved_short_and_cap_is_entry_cap():
    audit_trade(trade(), COSTS)
    with pytest.raises(ValueError, match="25%"):
        audit_trade(trade(26), COSTS)


@pytest.mark.parametrize(
    "change",
    [
        {"side": "long"},
        {"entry_time": "2026-10-10T00:00:00Z"},
        {"net_pnl": -20.0},
        {"entry_fee": 0.0},
        {"exit_fee": 0.0},
        {"target": 99.0},
        {"risk_budget": 1.0},
        {"slippage_cost": 0.0},
        {"spread_cost": 0.0},
        {"exit_price": float("nan")},
    ],
)
def test_reject_accounting_direction_timing_and_risk_corruption(change):
    with pytest.raises(ValueError):
        audit_trade(trade() | change, COSTS)


@pytest.mark.parametrize(
    "field,value",
    [
        ("trading_enabled", True),
        ("send_orders", True),
        ("allow_live_trading", True),
        ("mode", "demo_execution"),
        ("minimum_closed_trades_per_candidate", 10),
        ("maximum_drawdown_pct", 99.0),
        ("unknown_future_option", True),
    ],
)
def test_preregistration_rejects_orders_modes_and_relaxed_thresholds(field, value):
    raw = yaml.safe_load((ROOT / POLICY).read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        Protocol.model_validate(raw | {field: value})


def test_frozen_protocol_and_changed_source_refused(tmp_path):
    load_protocol(ROOT)
    raw = yaml.safe_load((ROOT / POLICY).read_text(encoding="utf-8"))
    raw["file_sha256"] = {"source.txt": "0" * 64}
    path = tmp_path / POLICY
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    (tmp_path / "source.txt").write_text("modified")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_protocol(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        checked_path(tmp_path, "../outside")


def test_future_boundary_precedes_collection_and_cannot_be_backdated(tmp_path):
    raw = yaml.safe_load((ROOT / POLICY).read_text(encoding="utf-8"))
    raw["earliest_signal_close_utc"] = raw["freeze_time_utc"]
    path = tmp_path / POLICY
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="preregistration"):
        load_protocol(tmp_path)


def test_overlaps_consumed_test_and_winner_not_fixed_region():
    rows = pd.DataFrame(
        [
            dict(
                evidence_source="recent",
                period="test",
                start="2025-07-01Z".replace("Z", "T00:00Z"),
                end="2026-09-26T00:00Z",
            ),
            dict(
                evidence_source="recent",
                period="diagnostic_year_2025",
                start="2025-01-01T00:00Z",
                end="2026-01-01T00:00Z",
            ),
        ]
    )
    catalog = evidence_catalog(rows)
    assert not catalog.independent_available.any()
    assert catalog[catalog.observed].overlapping_periods.str.len().gt(0).all()
    assert "consumed" in catalog.iloc[0].prior_use
    winner = pd.DataFrame(
        [dict(family="donchian_atr", evidence_source="recent", period="wf_0_test", scenario="base")]
    )
    assert neighbors(winner).empty
    pd.testing.assert_frame_equal(rows, deepcopy(rows))
