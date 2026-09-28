"""Incremental calls reuse the original strategy and original optional fill policy."""

from dataclasses import asdict

import pandas as pd

from quant_lab.config import MarketConfig, StrategyConfig
from quant_lab.execution_policies.optional_15m_fill import BaselineEntry, OptionalFillPolicy
from quant_lab.strategies.registry import StrategyRegistry


class StrategyAdapter:
    def __init__(self, risk, settlement_currency="USDC"):
        config = StrategyConfig(
            name="mtf_trend_pullback",
            enabled=True,
            risk=risk,
            market=MarketConfig(
                provider="okx_demo", symbol=f"ETH/{settlement_currency}", timeframe="1h"
            ),
            parameters={"architecture": "V1", "trade_mode": "LONG_ONLY"},
        )
        self.strategy = StrategyRegistry().discover().create(config)

    def evaluate(self, frame, boundary):
        closed = frame.loc[frame.index + pd.Timedelta(hours=1) <= boundary]
        features = self.strategy.prepare_features(closed)
        return self.strategy.generate_long_entries(features)[-1], features.iloc[-1]


class IncrementalTiming:
    def __init__(self, costs):
        self.policy = OptionalFillPolicy(
            pd.DataFrame(index=pd.DatetimeIndex([], tz="UTC")),
            [],
            pd.Timestamp("1970-01-01", tz="UTC"),
            pd.Timestamp("2200-01-01", tz="UTC"),
            "trend_pullback",
            costs,
        )

    def add(self, entry):
        self.policy.entries[entry.baseline_entry_time] = entry

    def decision(self, boundary, price, row, occupied):
        self.policy.rows = {boundary: row}
        return self.policy.decision(boundary, price, occupied)

    def snapshot(self):
        p = self.policy
        if p.attempt is not None:
            raise AssertionError("Complete or reject timing attempt before checkpoint")
        return {
            "last_time": p.last_time,
            "pending": [{**item, "entry": asdict(item["entry"])} for item in p.pending],
        }

    def restore(self, state):
        self.policy.last_time = pd.Timestamp(state["last_time"]) if state["last_time"] else None
        for raw in state["pending"]:
            entry = raw["entry"].copy()
            for key in ("baseline_signal_time", "baseline_entry_time"):
                entry[key] = pd.Timestamp(entry[key])
            record = raw["record"].copy()
            for key in ("baseline_signal_time", "baseline_entry_time"):
                record[key] = pd.Timestamp(record[key])
            item = {
                **raw,
                "entry": BaselineEntry(**entry),
                "record": record,
                "deadline": pd.Timestamp(raw["deadline"]),
                "touched": pd.Timestamp(raw["touched"]) if raw["touched"] else None,
            }
            self.policy.pending.append(item)
            self.policy.records.append(record)
