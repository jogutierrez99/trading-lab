"""Durable single-alternative demo execution; ambiguous submissions never retry."""

from decimal import Decimal
from uuid import uuid4

import pandas as pd

from quant_lab.execution_config import ExecutionConfig
from quant_lab.forward.store import encode, identity
from quant_lab.risk import CostModel, size_entry


class DemoCoordinator:
    def __init__(self, store, broker, strategy, instruments, settings):
        self.store, self.broker = store, broker
        self.strategy, self.instruments = strategy, instruments
        self.settings = settings

    def save_order(self, row):
        self.store.db.execute(
            "INSERT INTO orders VALUES (?,?,?,?) ON CONFLICT(stream,id) "
            "DO UPDATE SET data=excluded.data",
            (self.store.stream, row["client_id"], self.store.session, encode(row)),
        )

    def reconcile(self):
        for order in self.store.rows("orders"):
            if order["status"] in {"FILLED", "REJECTED"}:
                if order["status"] == "REJECTED":
                    raise RuntimeError("Rejected demo intent requires manual review")
                continue
            result = self.broker.by_client(order["instrument_id"], order["client_id"])
            if len(result) != 1:
                raise RuntimeError("Unknown demo submission; manual reconciliation required")
            exchange = result[0]
            fills = self.broker.get(
                "/api/v5/trade/fills",
                {"instId": order["instrument_id"], "ordId": exchange["ordId"]},
            )
            with self.store.db:
                for fill in fills:
                    self.store.put(
                        "fills",
                        identity(exchange["ordId"], fill["tradeId"]),
                        fill | {"strategy": self.strategy, "source": "OKX_DEMO"},
                    )
                order["exchange"] = exchange
                if exchange.get("state") in {"live", "partially_filled"}:
                    order["status"] = exchange["state"].upper()
                self.save_order(order)
            if exchange.get("state") != "filled":
                if exchange.get("state") in {"live", "partially_filled"}:
                    with self.store.db:
                        state = self.store.restore() or {}
                        state["demo_pending_order"] = order
                        self.store.checkpoint(state)
                    return False
                raise RuntimeError(
                    "Demo order pending/partial/canceled; manual reconciliation required"
                )
            if not fills or sum(Decimal(f["fillSz"]) for f in fills) != Decimal(order["contracts"]):
                raise RuntimeError("Incomplete fill ledger; manual reconciliation required")
            with self.store.db:
                for fill in fills:
                    self.store.put(
                        "fills",
                        identity(exchange["ordId"], fill["tradeId"]),
                        fill | {"strategy": self.strategy, "source": "OKX_DEMO"},
                    )
                state = self.store.restore() or {}
                state["demo_pending_order"] = None
                position = state.get("demo_position")
                qty = float(
                    Decimal(order["contracts"])
                    * self.instruments[order["instrument_id"]].contract_size
                )
                price = float(exchange["avgPx"])
                if order["exit"]:
                    if not position:
                        raise RuntimeError("Demo exit without owned position")
                    gross = (price - position["entry_price"]) * qty * position["direction"]
                    fees = position["fees"] + fills
                    currency = self.instruments[order["instrument_id"]].settlement_currency
                    net = (
                        gross + sum(float(f["fee"]) for f in fees)
                        if all(
                            f.get("feeCcy") == currency and f.get("fee") is not None for f in fees
                        )
                        else None
                    )
                    trade = dict(
                        position,
                        exit_price=price,
                        gross_pnl=gross,
                        fees_observed=position["fees"] + fills,
                        net_pnl_excluding_funding=net,
                        funding="unknown",
                        closed_at=exchange.get("uTime"),
                        holding_seconds=(int(exchange["uTime"]) - int(position["entry_timestamp"]))
                        / 1000,
                    )
                    state.setdefault("demo_trades", []).append(trade)
                    state["demo_equity_excluding_funding"] = (
                        state.get("demo_equity_excluding_funding", 10000.0) + net
                        if net is not None
                        else None
                    )
                    state["demo_position"] = None
                    kind = "DEMO_POSITION_CLOSED"
                else:
                    if position:
                        raise RuntimeError("Demo entry would duplicate owned exposure")
                    state["demo_position"] = dict(
                        strategy=self.strategy,
                        instrument_id=order["instrument_id"],
                        contracts=order["contracts"],
                        quantity=qty,
                        direction=1 if order["side"] == "buy" else -1,
                        entry_price=price,
                        fees=fills,
                        entry_order=exchange["ordId"],
                        entry_timestamp=exchange.get("uTime"),
                        mfe_pnl=0.0,
                        mae_pnl=0.0,
                        last_mark_price=price,
                    )
                    kind = "DEMO_ORDER_FILLED"
                order.update(status="FILLED", exchange=exchange)
                order["fill_price"] = price
                order["actual_quantity"] = qty
                order["sizing_deviation"] = qty - order["expected_quantity"]
                order["fees_observed"] = [
                    {"fee": f.get("fee"), "currency": f.get("feeCcy")} for f in fills
                ]
                order["position_after_fill"] = "FLAT" if order["exit"] else "OPEN"
                order["latency_ms"] = int(exchange["uTime"]) - int(
                    pd.Timestamp(order["submitted_at"]).timestamp() * 1000
                )
                order["slippage_bps"] = (
                    (price / order["reference_price"] - 1)
                    * 10000
                    * (1 if order["side"] == "buy" else -1)
                )
                order["slippage_difference_bps"] = (
                    (price / order["expected_price"] - 1)
                    * 10000
                    * (1 if order["side"] == "buy" else -1)
                )
                self.save_order(order)
                self.store.checkpoint(state)
                self.store.event(
                    kind, order["client_id"], order | {"timestamp": pd.Timestamp.now(tz="UTC")}
                )
                if order["exit"]:
                    self.store.event("DEMO_ORDER_FILLED", order["client_id"], order)
        return True

    def account_check(self):
        instrument = next(
            i
            for i in self.instruments
            if i.startswith("ETH-" if "eth" in self.strategy else "BTC-")
        )
        self.broker.account_ready(instrument)
        if not self.reconcile():
            return False
        state = self.store.restore() or {}
        owned = state.get("demo_position")
        expected = Decimal(owned["contracts"]) * owned["direction"] if owned else Decimal(0)
        positions = self.broker.get_positions()
        nonzero = [p for p in positions if Decimal(p.get("pos", "0")) != 0]
        if (
            any(p["instId"] != instrument or p.get("mgnMode") != "isolated" for p in nonzero)
            or sum(Decimal(p["pos"]) for p in nonzero) != expected
            or self.broker.get("/api/v5/trade/orders-pending", {})
        ):
            raise RuntimeError("Unowned/divergent demo account state; manual review required")
        return True

    def drain(self):
        if not self.account_check():
            return
        recorded = {r["intent_id"] for r in self.store.rows("orders")}
        # Only this session's timely intents can create an exchange submission.
        for intent in self.store.rows("order_intents", session=True):
            if intent["strategy"] != self.strategy or intent["id"] in recorded:
                continue
            if pd.Timestamp.now(tz="UTC") - pd.Timestamp(intent["timestamp"]) > pd.Timedelta(
                seconds=90
            ):
                raise RuntimeError("Expired demo intent; no retrospective submission")
            state = self.store.restore() or {}
            position = state.get("demo_position")
            exiting = intent["reason"] == "RMM_EXIT"
            if bool(position) != bool(exiting):
                raise RuntimeError("Shadow/demo occupancy diverged; manual review required")
            contracts = position["contracts"] if exiting else intent["contracts"]
            if not exiting:
                self.broker.entry_balance_ready()
                equity = state.get("demo_equity_excluding_funding", 10000.0)
                if equity is None:
                    raise RuntimeError("Unknown fee currency; demo sizing blocked")
                signal = next(
                    s for s in self.store.rows("signals") if s["signal_id"] == intent["id"]
                )
                instrument = self.instruments[intent["instrument_id"]]
                risk = self.settings.risk.model_copy(
                    update={
                        "sizing_method": "fixed_notional",
                        "position_pct": signal["calculated_exposure_pct"],
                    }
                )
                sized = size_entry(
                    equity,
                    intent["reference_price"],
                    0.0,
                    1 if intent["side"] == "buy" else -1,
                    risk,
                    ExecutionConfig(
                        filter_assumption="current OKX demo instrument metadata",
                        quantity_step=float(instrument.lot_size * instrument.contract_size),
                        min_quantity=float(instrument.min_size * instrument.contract_size),
                        min_notional=0.0,
                    ),
                    CostModel.from_config(self.settings.costs["base"]),
                )
                if isinstance(sized, str):
                    raise RuntimeError("Demo size rejected")
                contracts = instrument.convert(sized.price, target_quantity=sized.quantity)[
                    "contracts_rounded"
                ]
            row = dict(
                client_id="rmm" + identity(self.store.stream, intent["id"])[:29],
                intent_id=intent["id"],
                instrument_id=intent["instrument_id"],
                strategy=self.strategy,
                contracts=str(contracts),
                side=intent["side"],
                reference_price=intent["reference_price"],
                expected_price=intent["estimated_entry_price"],
                expected_quantity=intent["target_quantity"],
                signal_timestamp=intent["timestamp"],
                submitted_at=str(pd.Timestamp.now(tz="UTC")),
                exit=bool(exiting),
                status="SUBMITTING",
            )
            signal = next(s for s in self.store.rows("signals") if s["signal_id"] == intent["id"])
            row.update({k: signal[k] for k in ("bid", "ask", "quoted_spread_bps") if k in signal})
            with self.store.db:
                self.save_order(row)
            payload = dict(
                instId=row["instrument_id"],
                tdMode="isolated",
                posSide="net",
                side=row["side"],
                ordType="market",
                sz=row["contracts"],
                clOrdId=row["client_id"],
                reduceOnly=row["exit"],
            )
            try:
                answer = self.broker.submit(payload)
                if len(answer) != 1 or answer[0].get("sCode") != "0":
                    row["status"] = "REJECTED"
                    row["reject_code"] = answer[0].get("sCode") if len(answer) == 1 else "unknown"
                    with self.store.db:
                        self.save_order(row)
                        self.store.event("DEMO_ORDER_REJECTED", row["client_id"], row)
                    raise RuntimeError("Demo order rejected; review occupancy")
                with self.store.db:
                    self.store.event("DEMO_ORDER_SUBMITTED", row["client_id"], row)
            except Exception:
                with self.store.db:
                    self.store.event(
                        "DEMO_EXECUTION_BLOCKED",
                        uuid4().hex,
                        {"reason": "Reconcile durable client ID before proceeding"},
                    )
                raise
            self.reconcile()

    def observe(self, bar):
        """Closed-bar demo excursion bounds; never feed measurements into signals."""
        state = self.store.restore() or {}
        p = state.get("demo_position")
        if not p or bar.instrument_id != p["instrument_id"] or bar.timeframe != "4h":
            return
        if bar.timestamp < pd.Timestamp(int(p["entry_timestamp"]), unit="ms", tz="UTC"):
            return
        favorable, adverse = (bar.high, bar.low) if p["direction"] == 1 else (bar.low, bar.high)
        p["mfe_pnl"] = max(
            p["mfe_pnl"], (favorable - p["entry_price"]) * p["quantity"] * p["direction"]
        )
        p["mae_pnl"] = min(
            p["mae_pnl"], (adverse - p["entry_price"]) * p["quantity"] * p["direction"]
        )
        p["last_mark_price"] = bar.close
        p["unrealized_gross_pnl"] = (bar.close - p["entry_price"]) * p["quantity"] * p["direction"]
        p["as_of"] = str(bar.close_time)
        with self.store.db:
            self.store.checkpoint(state)
