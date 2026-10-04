"""Observational linear-contract accounting; never controls signals or routes orders."""

from dataclasses import asdict
from decimal import Decimal
from math import isclose, isfinite
from types import SimpleNamespace

import pandas as pd

from quant_lab.backtest import protective_fill
from quant_lab.forward.store import identity
from quant_lab.mtf_features import STEPS
from quant_lab.risk import CostModel


def monetary_pnl(side, entry, price, quantity):
    """Quantity is base units, not contracts, for validated linear instruments."""
    if side not in {"LONG", "SHORT"}:
        raise ValueError("Unsupported side")
    return (1 if side == "LONG" else -1) * (price - entry) * quantity


class ShadowTracker:
    def __init__(self, costs, max_holding_hours, emit=None, positions=None):
        self.config = costs
        self.costs = CostModel.from_config(costs)
        self.max_holding_hours = max_holding_hours
        self.emit = emit or (lambda *args: None)
        self.positions = positions or {}

    def open(self, intent, instrument, session, signal_id, signal_timestamp):
        raw = asdict(intent) if not isinstance(intent, dict) else intent
        for existing in self.positions.values():
            if existing["order_intent_id"] == raw["id"]:
                return existing
        key = identity("shadow_v1", session, raw["id"])
        if key in self.positions:
            return self.positions[key]
        contracts = Decimal(str(raw["contracts"]))
        if not contracts.is_finite():
            raise ValueError("Invalid contracts")
        quantity = float(contracts * instrument.contract_size)
        if (
            contracts <= 0
            or contracts % instrument.lot_size
            or contracts < instrument.min_size
            or not isclose(quantity, float(raw["target_quantity"]), rel_tol=1e-10)
        ):
            raise ValueError("Shadow contract/base quantity mismatch")
        if raw["side"] not in {"buy", "sell"}:
            raise ValueError("Invalid intent side")
        side = "LONG" if raw["side"] == "buy" else "SHORT"
        direction = 1 if side == "LONG" else -1
        entry, reference = float(raw["estimated_entry_price"]), float(raw["reference_price"])
        stop = float(raw["stop_price"])
        if (
            not all(isfinite(v) and v > 0 for v in (entry, reference, stop, quantity))
            or direction * (entry - stop) <= 0
        ):
            raise ValueError("Invalid shadow entry or stop")
        if not isclose(entry, self.costs.price(reference, direction), rel_tol=1e-10):
            raise ValueError("Intent price does not match inherited BASE costs")
        tf = "15m" if raw["execution_policy"] == "OPTIONAL_15M_FILL" else "1h"
        stamp = pd.Timestamp(raw["timestamp"])
        if stamp.tzinfo is None or stamp.utcoffset() != pd.Timedelta(0):
            raise ValueError("Shadow entry requires UTC")
        p = dict(
            shadow_position_id=key,
            session_id=session,
            signal_id=signal_id,
            order_intent_id=raw["id"],
            strategy=raw["strategy"],
            execution_policy=raw["execution_policy"],
            instrument=raw["instrument_id"],
            asset=raw["asset"],
            settlement_currency=instrument.settlement_currency,
            side=side,
            signal_timestamp=str(signal_timestamp) if signal_timestamp is not None else None,
            entry_timestamp=stamp.isoformat(),
            entry_time=stamp.isoformat(),
            entry_price=entry,
            reference_price=reference,
            quantity=quantity,
            contracts=str(contracts),
            contract_size=str(instrument.contract_size),
            notional=quantity * entry,
            initial_stop=float(raw["stop_price"]),
            current_stop=float(raw["stop_price"]),
            stop_price=float(raw["stop_price"]),
            risk_budget=float(raw["risk_budget"]),
            initial_risk=abs(entry - float(raw["stop_price"])) * quantity,
            status="OPEN",
            bars_held=0,
            max_holding_bars=int(self.max_holding_hours * 3600 / STEPS[tf].total_seconds()),
            management_timeframe=tf,
            holding_hours_limit=self.max_holding_hours,
            next_bar=stamp.floor(STEPS[tf]).isoformat(),
            as_of=stamp.isoformat(),
            current_price=reference,
            unrealized_pnl_gross=monetary_pnl(side, entry, reference, quantity),
            unrealized_pnl_net_estimate=None,
            realized_pnl_gross=None,
            realized_pnl_net=None,
            entry_fee=entry * quantity * self.costs.fee,
            entry_slippage=reference * quantity * self.config.slippage_pct / 100,
            entry_spread=reference * quantity * self.config.spread_pct / 200,
            exit_fee=0.0,
            exit_slippage=0.0,
            exit_spread=0.0,
            exit_cost=0.0,
            mfe_price=entry,
            mae_price=entry,
            mfe_pnl=0.0,
            mae_pnl=0.0,
            mfe_pct=0.0,
            mae_pct=0.0,
            mfe_r_multiple=0.0,
            mae_r_multiple=0.0,
            exit_timestamp=None,
            exit_time=None,
            exit_price=None,
            exit_reason=None,
            coverage="CONTINUOUS",
            excursion_quality="OHLC_OBSERVED",
            last_bar=None,
            cost_scenario="base",
            funding="not_modelled",
        )
        p["entry_cost"] = p["entry_fee"] + p["entry_slippage"] + p["entry_spread"]
        p["total_cost"] = p["entry_cost"]
        self.mark(p, reference)
        self.positions[key] = p
        self.emit("SHADOW_POSITION_OPENED", key, p.copy())
        return p

    def mark(self, p, reference):
        direction = 1 if p["side"] == "LONG" else -1
        exit_price = self.costs.price(reference, -direction)
        p["current_price"] = reference
        p["unrealized_pnl_gross"] = monetary_pnl(
            p["side"], p["entry_price"], reference, p["quantity"]
        )
        p["unrealized_pnl_net_estimate"] = (
            monetary_pnl(p["side"], p["entry_price"], exit_price, p["quantity"])
            - p["entry_fee"]
            - exit_price * p["quantity"] * self.costs.fee
        )
        p["estimated_exit_cost"] = p["quantity"] * (
            reference * self.costs.adverse + exit_price * self.costs.fee
        )
        p["distance_to_stop_pct"] = direction * (reference - p["current_stop"]) / reference * 100

    def excursion(self, p, high, low):
        favorable, adverse = (high, low) if p["side"] == "LONG" else (low, high)
        for name, price, better in (("mfe", favorable, max), ("mae", adverse, min)):
            value = monetary_pnl(p["side"], p["entry_price"], price, p["quantity"])
            if better(value, p[name + "_pnl"]) == value:
                p[name + "_price"], p[name + "_pnl"] = price, value
            p[name + "_pct"] = 100 * p[name + "_pnl"] / p["notional"]
            p[name + "_r_multiple"] = (
                p[name + "_pnl"] / p["initial_risk"] if p["initial_risk"] else None
            )

    def update(self, bar, *, continuity_verified=True):
        if not continuity_verified:
            return
        validate_bar(bar)
        for p in self.positions.values():
            if p["status"] != "OPEN" or (bar.instrument_id, bar.timeframe) != (
                p["instrument"],
                p["management_timeframe"],
            ):
                continue
            if p["coverage"] == "INDETERMINATE_ENTRY_BAR":
                continue
            expected = pd.Timestamp(p["next_bar"])
            if bar.timestamp < expected:
                continue
            if bar.timestamp > expected:
                p["coverage"] = "DATA_GAP"
                continue
            p["coverage"] = "CONTINUOUS"
            side = 1 if p["side"] == "LONG" else -1
            partial = bar.timestamp < pd.Timestamp(p["entry_timestamp"])
            touched = side * ((bar.low if side == 1 else bar.high) - p["current_stop"]) <= 0
            if partial and touched:
                p["coverage"] = "INDETERMINATE_ENTRY_BAR"
                p["unrealized_pnl_gross"] = p["unrealized_pnl_net_estimate"] = None
                self.emit(
                    "SHADOW_POSITION_UPDATED", identity(p["shadow_position_id"], bar.key), p.copy()
                )
                continue
            # No pre-entry extrema: partial first bar contributes its observed close only.
            if partial:
                p["excursion_quality"] = "PARTIAL_ENTRY_BAR_EXCLUDED"
                self.excursion(p, bar.close, bar.close)
                fill = None
            else:
                p["bars_held"] += 1
                fill = protective_fill(
                    bar, SimpleNamespace(stop=p["current_stop"], target=None), side
                )
                if fill:
                    # Intrabar order is unknown: never use extremes after the modeled stop.
                    self.excursion(p, max(bar.open, fill[0]), min(bar.open, fill[0]))
                    p["excursion_quality"] = "LOWER_BOUND_STOP_BAR"
                else:
                    self.excursion(p, bar.high, bar.low)
            p["next_bar"] = bar.close_time.isoformat()
            p["last_bar"] = bar.timestamp.isoformat()
            p["as_of"] = bar.close_time.isoformat()
            self.mark(p, bar.close)
            if fill or p["bars_held"] >= p["max_holding_bars"]:
                ref = fill[0] if fill else bar.close
                self.mark(p, ref)
                p["exit_reason"] = "STOP" if fill else "MAX_HOLDING"
                p["exit_timing"] = fill[2] if fill else "close"
                p["exit_bar_open"] = bar.timestamp.isoformat()
                # Intrabar timestamp unknown; observed_after is never advertised as exact fill time.
                p["exit_timestamp"] = (
                    bar.timestamp.isoformat()
                    if fill and fill[2] == "open"
                    else None
                    if fill
                    else bar.close_time.isoformat()
                )
                p["exit_time"] = p["exit_timestamp"]
                p["exit_observed_after"] = bar.close_time.isoformat()
                price = self.costs.price(ref, -side)
                p.update(status="CLOSED", exit_price=price, exit_reference_price=ref)
                p["realized_pnl_gross"] = monetary_pnl(
                    p["side"], p["entry_price"], price, p["quantity"]
                )
                p["exit_fee"] = price * p["quantity"] * self.costs.fee
                p["exit_slippage"] = ref * p["quantity"] * self.config.slippage_pct / 100
                p["exit_spread"] = ref * p["quantity"] * self.config.spread_pct / 200
                p["exit_cost"] = p["exit_fee"] + p["exit_slippage"] + p["exit_spread"]
                p["total_cost"] = p["entry_cost"] + p["exit_cost"]
                p["realized_pnl_net"] = p["realized_pnl_gross"] - p["entry_fee"] - p["exit_fee"]
                p["reference_pnl_gross"] = monetary_pnl(
                    p["side"], p["reference_price"], ref, p["quantity"]
                )
                p["unrealized_pnl_gross"] = p["unrealized_pnl_net_estimate"] = 0.0
                self.emit("SHADOW_POSITION_CLOSED", p["shadow_position_id"], p.copy())


def validate_bar(bar):
    if (
        bar.timeframe not in STEPS
        or bar.timestamp.tzinfo is None
        or bar.timestamp.utcoffset() != pd.Timedelta(0)
        or bar.timestamp.value % STEPS[bar.timeframe].value
        or not all(isfinite(v) and v > 0 for v in (bar.open, bar.high, bar.low, bar.close))
        or not isfinite(bar.volume)
        or bar.volume < 0
        or bar.low > min(bar.open, bar.close)
        or bar.high < max(bar.open, bar.close)
    ):
        raise ValueError("Invalid shadow OHLCV bar")
