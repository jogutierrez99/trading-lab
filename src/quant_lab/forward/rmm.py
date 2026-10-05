"""RMM decision policy for the existing ForwardEngine; no separate feed/runner/store."""

from dataclasses import asdict

import pandas as pd

from quant_lab.brokers.base import OrderIntent
from quant_lab.config import MarketConfig, StrategyConfig
from quant_lab.execution_config import ExecutionConfig
from quant_lab.forward.shadow import ShadowTracker
from quant_lab.forward.store import identity
from quant_lab.risk import size_entry
from quant_lab.strategies.risk_managed_momentum_v1 import RiskManagedMomentumV1Strategy


def descriptor(name):
    return (
        "ETH" if "eth" in name else "BTC",
        "LONG_ONLY" if "long_only" in name else "LONG_SHORT",
        "SHADOW_CANDIDATE" if name.endswith("shadow") else "MAIN",
    )


class RMMPolicy:
    def __init__(self, engine):
        self.e = engine
        state = engine.store.restore() or {}
        engine.positions = state.get("positions", {s: None for s in engine.config.strategies})
        engine.equity = state.get("equity", {s: 10000.0 for s in engine.config.strategies})
        engine.shadow = ShadowTracker(
            engine.inherited.costs["base"],
            None,
            engine.store.event,
            state.get("shadow_positions", {}),
        )
        engine.monitor_latest = state.get("monitor_latest", {})
        self.adapters = {}
        for asset in engine.config.instruments:
            self.adapters[asset] = RiskManagedMomentumV1Strategy(
                StrategyConfig(
                    name="risk_managed_momentum_v1",
                    enabled=True,
                    risk=engine.inherited.risk,
                    market=MarketConfig(
                        provider="okx_demo", symbol=asset + "/USDT", timeframe="4h"
                    ),
                    parameters=engine.config.parameters,
                )
            )

    def save(self):
        state = self.e.store.restore() or {}
        self.e.store.checkpoint(
            state
            | dict(
                positions=self.e.positions,
                equity=self.e.equity,
                monitor_latest=self.e.monitor_latest,
                shadow_positions=self.e.shadow.positions,
            )
        )

    def decision(self, asset, boundary):
        frame = self.e.book.frame(self.e.config.instruments[asset], "4h")
        frame = frame.loc[frame.index + pd.Timedelta(hours=4) <= boundary]
        strategy = self.adapters[asset]
        features = strategy.prepare_features(frame)
        signals = strategy.generate_signals(frame)
        row = features.iloc[-1]
        return row, dict(
            long=signals.long_entries[-1],
            short=signals.short_entries[-1],
            exit_long=signals.long_exits[-1],
            exit_short=signals.short_exits[-1],
        )

    def ingest(self, bar, quote_provider, recovering):
        e = self.e
        if bar.timeframe != "4h" or bar.instrument_id not in e.config.instruments.values():
            with e.store.db:
                e.observe(bar)
                self.save()
            return
        if e.store.gaps(unresolved=True) and not recovering:
            with e.store.db:
                e.store.event("SIGNAL_BLOCKED_DATA_GAP", bar.key, {"timestamp": bar.close_time})
            return
        with e.store.db:
            if not e.remember(bar):
                e.store.event(
                    "DUPLICATE_SIGNAL_PREVENTED",
                    identity(bar.key, e.store.session),
                    {"timestamp": bar.close_time},
                )
                return
            e.shadow.update(bar)
            asset = next(k for k, v in e.config.instruments.items() if v == bar.instrument_id)
            if len(e.book.frame(bar.instrument_id, "4h")) < e.config.warmup_bars:
                e.store.event("SIGNAL_REJECTED", bar.key, {"reason": "warmup_incomplete"})
                self.save()
                return
            row, signals = self.decision(asset, bar.close_time)
            e.store.event(
                "RMM_CANDLE_EVALUATED",
                bar.key,
                dict(
                    timestamp=bar.close_time,
                    symbol=asset,
                    timeframe="4h",
                    recovering=recovering,
                    momentum=float(row.momentum),
                    ema=float(row.ema),
                    realized_volatility=float(row.realized_volatility),
                    **signals,
                ),
            )
            if recovering:
                if any(e.positions[s] is not None for s in e.config.strategies):
                    e.store.event(
                        "RECOVERY_REVIEW_REQUIRED",
                        bar.key,
                        {"reason": "missed execution boundary; no retrospective orders"},
                    )
                self.save()
                return
            for name in e.config.strategies:
                symbol, mode, role = descriptor(name)
                if symbol != asset:
                    continue
                position = e.positions[name]
                exiting = (
                    position and signals["exit_long" if position["side"] == "buy" else "exit_short"]
                )
                side = (
                    -1 if signals["short"] and mode == "LONG_SHORT" else 1 if signals["long"] else 0
                )
                if not exiting and (position is not None or not side):
                    continue
                try:
                    quote, observed = quote_provider(bar.instrument_id, bar.close_time)
                except ValueError:
                    e.store.event(
                        "QUOTE_UNAVAILABLE",
                        identity(name, bar.key),
                        {"strategy": name, "reason": "no valid causal quote"},
                    )
                    continue
                if not bar.close_time <= observed <= bar.close_time + pd.Timedelta(seconds=90):
                    raise ValueError("Quote outside decision window")
                signal_id = identity(
                    name, "1.0.0", bar.instrument_id, bar.close_time, "exit" if exiting else side
                )
                instrument = e.instruments[bar.instrument_id]
                fraction = min(0.25, max(0.05, 0.10 / float(row.realized_volatility)))
                if exiting:
                    intent = OrderIntent(
                        signal_id,
                        str(observed),
                        name,
                        asset,
                        bar.instrument_id,
                        "sell" if position["side"] == "buy" else "buy",
                        "market_hypothetical",
                        position["target_quantity"] * quote,
                        position["target_quantity"],
                        position["contracts"],
                        quote,
                        e.costs.price(quote, -1 if position["side"] == "buy" else 1),
                        None,
                        None,
                        "RMM_EXIT",
                        "RMM_SIGNAL_4H",
                    )
                    closed = e.shadow.signal_close(position["shadow_id"], quote, observed)
                    e.equity[name] += closed["realized_pnl_net"]
                    e.positions[name] = None
                else:
                    risk = e.inherited.risk.model_copy(
                        update={"sizing_method": "fixed_notional", "position_pct": fraction * 100}
                    )
                    execution = ExecutionConfig(
                        filter_assumption="current OKX demo instrument metadata",
                        quantity_step=float(instrument.lot_size * instrument.contract_size),
                        min_quantity=float(instrument.min_size * instrument.contract_size),
                        min_notional=0.0,
                    )
                    sized = size_entry(e.equity[name], quote, 0.0, side, risk, execution, e.costs)
                    if isinstance(sized, str):
                        e.store.event(
                            "SIGNAL_REJECTED", signal_id, {"strategy": name, "reason": sized}
                        )
                        continue
                    contracts = instrument.convert(sized.price, target_quantity=sized.quantity)[
                        "contracts_rounded"
                    ]
                    intent = OrderIntent(
                        signal_id,
                        str(observed),
                        name,
                        asset,
                        bar.instrument_id,
                        "buy" if side == 1 else "sell",
                        "market_hypothetical",
                        sized.quantity * sized.price,
                        sized.quantity,
                        contracts,
                        quote,
                        sized.price,
                        None,
                        None,
                        "RMM_ENTRY",
                        "RMM_SIGNAL_4H",
                    )
                    p = e.shadow.open(
                        intent, instrument, e.store.session, signal_id, bar.close_time
                    )
                    e.positions[name] = asdict(intent) | {"shadow_id": p["shadow_position_id"]}
                data = dict(
                    timestamp=bar.close_time,
                    strategy=name,
                    symbol=asset,
                    timeframe="4h",
                    mode=mode,
                    role=role,
                    side=intent.side,
                    signal_id=signal_id,
                    reference_price=quote,
                    momentum=float(row.momentum),
                    ema=float(row.ema),
                    realized_volatility=float(row.realized_volatility),
                    target_volatility_pct=10.0,
                    calculated_exposure_pct=fraction * 100,
                    target_notional=intent.target_notional,
                    quantity=intent.target_quantity,
                )
                provider = getattr(quote_provider, "__self__", None)
                data.update(getattr(provider, "last_quotes", {}).get(bar.instrument_id, {}))
                e.store.event("SIGNAL_GENERATED", signal_id, data)
                e.store.event("ORDER_INTENT_CREATED", signal_id, asdict(intent))
                e.store.event(
                    "POSITION_SNAPSHOT",
                    signal_id,
                    dict(
                        strategy=name,
                        source="HYPOTHETICAL",
                        status="closed" if exiting else "open",
                        equity=e.equity[name],
                        timestamp=observed,
                    ),
                )
            self.save()
