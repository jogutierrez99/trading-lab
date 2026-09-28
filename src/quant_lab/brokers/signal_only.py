"""Hypothetical intents are recorded explicitly, never passed to place_order."""

from dataclasses import asdict

from quant_lab.brokers.base import ReadOnlyBroker


class SignalOnlyBroker(ReadOnlyBroker):
    def __init__(self, instruments, record):
        self.instruments, self.record = instruments, record

    def record_intent(self, intent):
        self.record("ORDER_INTENT_CREATED", intent.id, asdict(intent))
        self.record("ORDER_SKIPPED_SIGNAL_ONLY", intent.id, {"strategy": intent.strategy})

    def get_balance(self):
        return {"source": "not_an_exchange_account", "balance": None}

    def get_positions(self):
        return []

    def get_open_orders(self):
        return []

    def get_fills(self):
        return []

    def get_order(self, instrument_id, order_id):
        return None

    def get_instruments(self):
        return list(self.instruments.values())

    def get_instrument(self, instrument_id):
        return self.instruments[instrument_id]
