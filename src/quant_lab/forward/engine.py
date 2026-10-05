"""Closed-candle signal engine, theoretical risk and durable shadow occupancy.

Shadow accounts are independent alternatives. No broker mutation is called.
"""

from dataclasses import asdict
from decimal import Decimal

import pandas as pd

from quant_lab.brokers.base import OrderIntent
from quant_lab.brokers.signal_only import SignalOnlyBroker
from quant_lab.execution_config import ExecutionConfig
from quant_lab.execution_policies.optional_15m_fill import BaselineEntry
from quant_lab.forward.shadow import ShadowTracker, monetary_pnl
from quant_lab.forward.store import identity
from quant_lab.forward.strategy import IncrementalTiming, StrategyAdapter
from quant_lab.market_data.okx import Bar, CandleBook, QuoteUnavailable
from quant_lab.mtf_features import STEPS, complete_bars
from quant_lab.optional_fill_execution import quarter_features
from quant_lab.risk import CostModel, size_entry

BASELINE = "eth_trend_pullback_v1"
OPTIONAL = "eth_trend_pullback_v1_optional_15m_fill"


class ForwardEngine:
    def __init__(self, config, inherited, instruments, store):
        self.config, self.inherited, self.instruments, self.store = (
            config,
            inherited,
            instruments,
            store,
        )
        self.book = CandleBook()
        if config.data_protocol == "rmm_4h":
            from quant_lab.forward.rmm import RMMPolicy

            self.costs = CostModel.from_config(inherited.costs["base"])
            self.eth = config.instruments.get("ETH")
            for row in store.rows("bars"):
                self.book.add(Bar(**(row | {"timestamp": pd.Timestamp(row["timestamp"])})))
            self.rmm = RMMPolicy(self)
            return
        self.adapter = StrategyAdapter(
            inherited.risk, instruments[config.instruments["ETH"]].settlement_currency
        )
        self.costs = CostModel.from_config(inherited.costs["base"])
        self.timing = IncrementalTiming(inherited.costs["base"])
        self.broker = SignalOnlyBroker(instruments, store.event)
        self.positions = {BASELINE: None, OPTIONAL: None}
        self.monitor_latest = {}
        self.equity = {BASELINE: inherited.capital, OPTIONAL: inherited.capital}
        self.eth = config.instruments["ETH"]
        for row in store.rows("bars"):
            self.book.add(Bar(**(row | {"timestamp": pd.Timestamp(row["timestamp"])})))
        state = store.restore()
        if state:
            self.positions, self.equity = state["positions"], state["equity"]
            self.monitor_latest = state.get("monitor_latest", {})
            self.timing.restore(state["timing"])
        self.shadow = ShadowTracker(
            inherited.costs["base"],
            inherited.risk.max_holding_bars,
            store.event,
            state.get("shadow_positions", {}) if state else {},
        )

    def save(self):
        if hasattr(self, "rmm"):
            return self.rmm.save()
        self.store.checkpoint(
            {
                "positions": self.positions,
                "equity": self.equity,
                "timing": self.timing.snapshot(),
                "monitor_latest": self.monitor_latest,
                "shadow_positions": self.shadow.positions,
            }
        )

    def remember(self, bar):
        if self.book.add(bar):
            self.store.event("MARKET_BAR_CLOSED", bar.key, bar.row())
            return True
        return False

    def bootstrap(self, bars):
        with self.store.db:
            for bar in sorted(bars, key=lambda b: (b.instrument_id, b.timeframe, b.timestamp)):
                if self.config.required_feed(bar.instrument_id, bar.timeframe):
                    self.remember(bar)
                else:
                    self.observe(bar)
            self.save()

    def monitoring_warning(self, instrument, timeframe, reason):
        self.store.event(
            "MONITORING_WARNING",
            identity(self.store.session, instrument, timeframe, reason),
            {
                "instrument": instrument,
                "timeframe": timeframe,
                "reason": reason,
                "blocks_eth_v1": False,
            },
        )

    def observe(self, bar):
        """Record observed bars separately from the strategy's continuous book."""
        key = f"{bar.instrument_id}|{bar.timeframe}"
        previous = self.monitor_latest.get(key)
        if previous:
            stamp = pd.Timestamp(previous["timestamp"])
            if bar.timestamp <= stamp:
                return
            if bar.timestamp - stamp != STEPS[bar.timeframe]:
                self.monitoring_warning(
                    bar.instrument_id, bar.timeframe, f"Observation gap after {stamp.isoformat()}"
                )
        self.store.event("MONITOR_BAR_CLOSED", bar.key, bar.row())
        self.monitor_latest[key] = bar.row() | {"timestamp": bar.timestamp.isoformat()}

    def invalidate_timing(self, reason):
        if hasattr(self, "rmm"):
            return
        with self.store.db:
            for item in self.timing.policy.pending:
                self.store.event("TIMING_NOT_EXECUTED", item["entry"].signal_id, {"reason": reason})
            self.timing.policy.finalize(pd.Timestamp.now(tz="UTC"), reason)
            self.save()

    def sized_intent(self, strategy, signal_id, boundary, quote, observed, atr):
        instrument = self.instruments[self.eth]
        execution = ExecutionConfig(
            quantity_step=float(instrument.lot_size * instrument.contract_size),
            min_quantity=float(instrument.min_size * instrument.contract_size),
            min_notional=0.0,
            filter_assumption="current OKX demo instrument metadata",
        )
        sized = size_entry(
            self.equity[strategy],
            quote,
            atr * self.inherited.risk.atr_multiplier,
            1,
            self.inherited.risk,
            execution,
            self.costs,
        )
        if isinstance(sized, str):
            self.store.event(
                "SIGNAL_REJECTED",
                identity(signal_id, strategy, boundary),
                {"reason": sized, "strategy": strategy},
            )
            return None
        # Long stop rounds upward, never increasing the risk assumed by size_entry.
        stop = float(instrument.round_price(sized.stop, upward=True))
        if not 0 < stop < sized.price:
            self.store.event(
                "SIGNAL_REJECTED",
                identity(signal_id, strategy, boundary),
                {"reason": "invalid_tick_stop", "strategy": strategy},
            )
            return None
        conversion = instrument.convert(sized.price, target_quantity=sized.quantity)
        quantity = float(Decimal(conversion["contracts_rounded"]) * instrument.contract_size)
        key = identity(signal_id, strategy)
        intent = OrderIntent(
            key,
            observed.isoformat(),
            strategy,
            "ETH",
            self.eth,
            "buy",
            "market_hypothetical",
            quantity * sized.price,
            quantity,
            conversion["contracts_rounded"],
            quote,
            sized.price,
            stop,
            sized.risk_budget,
            "original V1 long signal",
            "OPTIONAL_15M_FILL" if strategy == OPTIONAL else "BASELINE",
        )
        self.store.event(
            "POSITION_SIZE_CALCULATED",
            identity(key, boundary),
            {**conversion, "strategy": strategy, "decision_close": boundary},
        )
        self.store.event(
            "STOP_CALCULATED",
            identity(key, boundary),
            {"stop": stop, "atr": atr, "risk_budget": sized.risk_budget},
        )
        return intent

    def accept(self, intent, boundary, *, publish=True, signal_id=None, signal_timestamp=None):
        if publish:
            self.broker.record_intent(intent)
            self.shadow.open(
                intent,
                self.instruments[intent.instrument_id],
                self.store.session,
                signal_id,
                signal_timestamp or boundary,
            )
        self.positions[intent.strategy] = asdict(intent) | {"entry_boundary": boundary.isoformat()}
        self.store.event(
            "POSITION_SNAPSHOT",
            intent.id,
            {
                "source": "theoretical_shadow",
                "status": "open",
                "entry_equity": self.equity[intent.strategy],
                "exposure_pct": 100 * intent.target_notional / self.equity[intent.strategy],
                **self.positions[intent.strategy],
            },
        )

    def update_position(self, strategy, bar):
        position = self.positions[strategy]
        if position is None or bar.timestamp < pd.Timestamp(position["entry_boundary"]):
            return
        stop = position["stop_price"]
        reason, reference = None, None
        if bar.low <= stop:
            reason, reference = "theoretical_stop", min(bar.open, stop)
        elif bar.close_time - pd.Timestamp(position["entry_boundary"]) >= pd.Timedelta(
            hours=self.inherited.risk.max_holding_bars
        ):
            reason, reference = "theoretical_holding_limit", bar.close
        if reason:
            price = self.costs.price(reference, -1)
            quantity, entry = position["target_quantity"], position["estimated_entry_price"]
            self.equity[strategy] += (
                monetary_pnl("LONG", entry, price, quantity)
                - quantity * (entry + price) * self.costs.fee
            )
            self.positions[strategy] = None
            self.store.event(
                "SHADOW_POSITION_CLOSED",
                identity(position["id"], bar.key),
                {
                    "strategy": strategy,
                    "reason": reason,
                    "price_estimate": price,
                    "observed_after": bar.close_time,
                    "funding": "not_modelled",
                },
            )
            self.store.event(
                "POSITION_SNAPSHOT",
                identity(position["id"], bar.key, "closed"),
                {
                    "source": "theoretical_shadow",
                    "status": "closed",
                    "strategy": strategy,
                    "timestamp": bar.close_time,
                    "equity": self.equity[strategy],
                    "exposure_pct": 0.0,
                },
            )

    def ingest(self, bar, quote_provider, *, recovering=False):
        if hasattr(self, "rmm"):
            return self.rmm.ingest(bar, quote_provider, recovering)
        if not recovering and self.config.required_feed(bar.instrument_id, bar.timeframe):
            gaps = self.store.gaps(unresolved=True)
            if gaps:
                with self.store.db:
                    self.store.event(
                        "SIGNAL_BLOCKED_DATA_GAP",
                        bar.key,
                        {
                            "instrument": bar.instrument_id,
                            "timeframe": bar.timeframe,
                            "timestamp": bar.close_time,
                            "incidents": [g["event_id"] for g in gaps],
                        },
                    )
                return
        with self.store.db:
            if not self.config.required_feed(bar.instrument_id, bar.timeframe):
                self.observe(bar)
                self.save()
                return
            if not self.remember(bar):
                return
            if bar.instrument_id != self.eth or bar.timeframe != "15m":
                self.save()
                return
            boundary = bar.close_time
            quarters = self.book.frame(self.eth, "15m")
            hourly = None
            if boundary.minute == 0:
                assembled = complete_bars(quarters.tail(4), "15m", "1h")
                if len(assembled):
                    stamp = assembled.index[-1]
                    hourly = Bar(self.eth, "1h", stamp, **assembled.iloc[-1].to_dict())
                    # Prefer an already available native hourly bar.
                    existing = self.book.bars.get((self.eth, "1h"), {}).get(stamp)
                    if existing:
                        hourly = existing
                    else:
                        self.remember(hourly)
            if hourly:
                self.update_position(BASELINE, hourly)
                self.shadow.update(hourly)
            self.update_position(OPTIONAL, bar)
            self.shadow.update(bar)
            if recovering:
                self.store.event("LATE_CANDLE", bar.key, {"reason": "recovery_context_only"})
                self.save()
                return
            hours = self.book.frame(self.eth, "1h")
            if len(hours) < self.config.warmup_bars or len(quarters) < self.config.warmup_bars:
                self.store.event("SIGNAL_REJECTED", bar.key, {"reason": "warmup_incomplete"})
                self.save()
                return
            signal, row = self.adapter.evaluate(hours, boundary) if hourly else (False, None)
            signal_id = identity("mtf_trend_pullback", "1.0.0", "V1", self.eth, boundary, "long")
            if signal:
                self.store.event(
                    "SIGNAL_GENERATED",
                    signal_id,
                    {
                        "timestamp": boundary,
                        "strategy": "mtf_trend_pullback_v1",
                        "instrument": self.eth,
                        "side": "long",
                        "signal_id": signal_id,
                    },
                )
            if not signal and not self.timing.policy.pending:
                self.save()
                return
            try:
                quote, observed = quote_provider(self.eth, boundary)
            except QuoteUnavailable as exc:
                self.store.event("QUOTE_UNAVAILABLE", bar.key, exc.details)
                if signal:
                    self.store.event(
                        "SIGNAL_REJECTED",
                        signal_id,
                        {
                            "reason": "quote_unavailable",
                            "quote_reason": str(exc),
                            "timestamp": boundary,
                        },
                    )
                # A missing timing observation cannot be retried at a later candle.
                # Keep the original policy, explicitly cancel affected pending entries.
                for item in self.timing.policy.pending:
                    self.store.event(
                        "TIMING_NOT_EXECUTED",
                        item["entry"].signal_id,
                        {"reason": "quote_unavailable"},
                    )
                self.timing.policy.finalize(boundary, "quote_unavailable")
                self.save()
                return
            if not boundary <= observed <= boundary + pd.Timedelta(seconds=90):
                raise ValueError("Quote is not causally available within the decision window")
            # Older pending opportunities always precede a new hourly signal.
            qrow = quarter_features(quarters).iloc[-1].to_dict()
            self.advance_timing(boundary, quote, observed, qrow)
            if signal and self.positions[BASELINE] is None:
                intent = self.sized_intent(
                    BASELINE, signal_id, boundary, quote, observed, float(row.risk_atr)
                )
                if intent:
                    self.accept(
                        intent,
                        boundary,
                        publish=BASELINE in self.config.strategies,
                        signal_id=signal_id,
                        signal_timestamp=boundary,
                    )
                    if OPTIONAL in self.config.strategies:
                        entry = BaselineEntry(
                            intent.id,
                            signal_id,
                            boundary,
                            boundary,
                            intent.estimated_entry_price,
                            float(row.risk_atr),
                            float(row.risk_atr) * self.inherited.risk.atr_multiplier,
                            float(row.ema50),
                            float(row.ema50),
                        )
                        self.timing.add(entry)
                        # The policy treats a repeated decision time as a gap.
                        self.timing.policy.last_time = None
                        self.timing.decision(
                            boundary, quote, qrow, self.positions[OPTIONAL] is not None
                        )
                        self.store.event(
                            "TIMING_WINDOW_STARTED",
                            signal_id,
                            {
                                "baseline_entry": intent.estimated_entry_price,
                                "deadline": boundary + STEPS["1h"],
                            },
                        )
            elif signal:
                self.store.event(
                    "SIGNAL_REJECTED", signal_id, {"reason": "shadow_baseline_position_capacity"}
                )
            self.save()

    def advance_timing(self, boundary, quote, observed, qrow):
        if not self.timing.policy.pending:
            return
        previous = list(self.timing.policy.pending)
        decision = self.timing.decision(boundary, quote, qrow, self.positions[OPTIONAL] is not None)
        for item in previous:
            if item["record"]["status"] == "NOT_EXECUTED":
                self.store.event(
                    "TIMING_NOT_EXECUTED",
                    item["entry"].signal_id,
                    {"reason": item["record"]["non_execution_reason"]},
                )
        if decision:
            item, optimized = self.timing.policy.attempt
            entry = item["entry"]
            intent = self.sized_intent(
                OPTIONAL, entry.signal_id, boundary, quote, observed, entry.signal_atr
            )
            if intent:
                self.accept(
                    intent,
                    boundary,
                    signal_id=entry.signal_id,
                    signal_timestamp=entry.baseline_signal_time,
                )
                self.timing.policy.on_entry(boundary, intent.estimated_entry_price)
                self.store.event(
                    "TIMING_FILL_SELECTED" if optimized else "TIMING_FALLBACK",
                    intent.id,
                    {**item["record"], "strategy": OPTIONAL, "quote_observed_at": observed},
                )
            else:
                self.timing.policy.reject_attempt(boundary)
                if boundary >= item["deadline"]:
                    self.timing.policy.pending.remove(item)
                    self.store.event(
                        "TIMING_NOT_EXECUTED", entry.signal_id, {"reason": "engine_risk_rejection"}
                    )
