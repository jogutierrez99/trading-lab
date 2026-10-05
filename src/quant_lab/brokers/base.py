"""Shared broker interface and exchange-independent hypothetical intent."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class OrderIntent:
    id: str
    timestamp: str
    strategy: str
    asset: str
    instrument_id: str
    side: str
    order_type: str
    target_notional: float
    target_quantity: float
    contracts: str
    reference_price: float
    estimated_entry_price: float
    stop_price: float | None
    risk_budget: float | None
    reason: str
    execution_policy: str


class TradingDisabled(RuntimeError):
    """All exchange mutations are unavailable in this release."""


class Broker(Protocol):
    def get_balance(self): ...
    def get_positions(self): ...
    def get_position(self, instrument_id): ...
    def get_open_orders(self): ...
    def place_order(self, intent): ...
    def cancel_order(self, order_id): ...
    def get_order(self, instrument_id, order_id): ...
    def get_fills(self): ...
    def close_position(self, instrument_id): ...
    def get_instrument(self, instrument_id): ...
    def get_instruments(self): ...
    def reconcile(self): ...


class ReadOnlyBroker:
    def place_order(self, intent):
        raise TradingDisabled("Order routing is not implemented, including DEMO_EXECUTION")

    def cancel_order(self, order_id):
        raise TradingDisabled("Order cancellation is disabled")

    def close_position(self, instrument_id):
        raise TradingDisabled("Closing exchange positions is disabled")

    def get_position(self, instrument_id):
        return [p for p in self.get_positions() if p["instId"] == instrument_id]

    def reconcile(self):
        return {
            "balance": self.get_balance(),
            "positions": self.get_positions(),
            "open_orders": self.get_open_orders(),
            "fills": self.get_fills(),
        }
