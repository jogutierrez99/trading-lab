"""Twelve independent synthetic accounts; no broker capability in this engine."""

import json
import sqlite3
from dataclasses import asdict
from math import isfinite
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from quant_lab.backtest import protective_fill
from quant_lab.forward.store import Store, encode, identity
from quant_lab.market_data.okx import Bar, CandleBook, DataGap, parse_bar
from quant_lab.risk import CostModel, SizedEntry, size_entry

DISCLAIMER = "SIGNAL_ONLY — HYPOTHETICAL — NO EXCHANGE ORDER"


def utc(value):
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None or stamp.utcoffset() != pd.Timedelta(0):
        raise ValueError("UTC timestamp required")
    return stamp


def validate_bar(bar, instrument, now):
    if bar.instrument_id != instrument or bar.timeframe != "1h":
        raise ValueError("Unexpected instrument/timeframe")
    stamp = utc(bar.timestamp)
    raw = [
        str(stamp.value // 1_000_000),
        *map(str, (bar.open, bar.high, bar.low, bar.close)),
        "0",
        str(bar.volume),
        "0",
        "1",
    ]
    parse_bar(instrument, "1h", raw, utc(now))


class DonchianStore(Store):
    """Same tested OS lock/WAL/event contract, in a dedicated root only."""

    def report(self, status):
        self.metadata["status"] = status
        if status != "running":
            self.metadata["end"] = pd.Timestamp.now(tz="UTC").isoformat()
        self.db.execute(
            "UPDATE sessions SET data=? WHERE id=?", (encode(self.metadata), self.session)
        )
        self.db.commit()
        (self.path / "session.json").write_text(encode(self.metadata), encoding="utf-8")


class DonchianEngine:
    def __init__(self, store, candidates, costs, execution, instrument, nominal_start, started):
        self.store, self.candidates, self.cost_configs = store, candidates, costs
        self.costs = {s: CostModel.from_config(c) for s, c in costs.items()}
        self.execution, self.instrument = execution, instrument
        self.started, self.nominal = utc(started), utc(nominal_start)
        self.book = CandleBook()
        restored = store.restore()
        expected_accounts = {f"{n}|{s}" for n in candidates for s in costs}
        if restored and (
            restored.get("schema") != 1 or set(restored.get("accounts", {})) != expected_accounts
        ):
            raise ValueError("Incomplete/incompatible checkpoint; never reset missing accounts")
        self.state = restored or dict(
            schema=1,
            candles=[],
            accounts={},
            pending={},
            last_closed=None,
            effective_start=None,
            gap=False,
            gap_number=0,
            review_required=False,
            paused=False,
            started=self.started.isoformat(),
        )
        for row in self.state["candles"]:
            self.book.add(Bar(**(row | {"timestamp": utc(row["timestamp"])})))
        if restored:
            frame = self.book.frame(instrument, "1h")
            if len(frame) < 1000 or frame.index[-1] != utc(self.state["last_closed"]):
                raise ValueError("Checkpoint signal context is incomplete")
            for account in self.state["accounts"].values():
                if not all(
                    isfinite(account[k]) for k in ("balance", "equity", "peak", "realized_net")
                ):
                    raise ValueError("Invalid checkpoint account values")
        for candidate in candidates:
            for scenario in costs:
                self.state["accounts"].setdefault(
                    f"{candidate}|{scenario}",
                    dict(
                        balance=10000.0,
                        equity=10000.0,
                        peak=10000.0,
                        max_drawdown_pct=0.0,
                        position=None,
                        closed_trades=0,
                        eligible_closed_trades=0,
                        realized_net=0.0,
                        fees_paid=0.0,
                    ),
                )

    def emit(self, kind, key, **data):
        self.store.event(
            kind,
            identity(self.store.stream, key),
            dict(
                disclaimer=DISCLAIMER,
                mode="signal_only",
                side="SHORT",
                instrument=self.instrument,
                timeframe="1h",
            )
            | data,
        )

    def checkpoint(self):
        self.state["candles"] = [
            b.row() for b in self.book.bars.get((self.instrument, "1h"), {}).values()
        ]
        self.store.checkpoint(self.state)

    def bootstrap(self, bars, now):
        if self.state["last_closed"] is not None:
            raise ValueError("Cannot bootstrap over persisted accounts")
        if len(bars) < 1000:
            raise DataGap("1000 confirmed continuous hours required")
        for bar in bars:
            validate_bar(bar, self.instrument, now)
            self.book.add(bar)
        if bars[-1].close_time != utc(now).floor("h"):
            raise DataGap("Warmup is stale")
        # Warmup signals never become prospectively executable signals.
        self.state["last_closed"] = bars[-1].timestamp.isoformat()
        with self.store.db:
            self.emit("WARMUP_VALIDATED", "warmup", timestamp=utc(now), count=len(bars))
            self.checkpoint()

    def missed(self, candidate, reason, now):
        pending = self.state["pending"].pop(candidate, None)
        if pending:
            self.emit(
                "MISSED_ENTRY",
                f"missed|{candidate}|{pending['close']}",
                candidate=candidate,
                timestamp=now,
                signal_close=pending["close"],
                reason=reason,
                notify=True,
            )

    def gap(self, reason, now):
        with self.store.db:
            if not self.state["gap"]:
                self.state["gap_number"] += 1
                self.emit(
                    "DATA_GAP",
                    f"gap|{self.state['gap_number']}",
                    timestamp=now,
                    reason=reason,
                    last_closed=self.state["last_closed"],
                    notify=True,
                )
            self.state["gap"] = True
            self.state["review_required"] = True
            for account in self.state["accounts"].values():
                if account["position"]:
                    account["position"]["coverage"] = "REST_RECONSTRUCTED"
            for candidate in list(self.state["pending"]):
                self.missed(candidate, "data_gap_or_disconnect", now)
            self.checkpoint()

    def recover(self, bars, now):
        """Confirmed OHLC restores known positions, never creates historical entries."""
        last = utc(self.state["last_closed"])
        if not bars or bars[0].timestamp != last or bars[-1].close_time != utc(now).floor("h"):
            raise DataGap("Recovery must span checkpoint through latest confirmed hour")
        if len(bars) == 1 and not self.state["gap"]:
            self.closed(bars[0], now, recovering=True)
            return
        self.gap("restart_or_feed_recovery", now)
        for bar in bars:
            self.closed(bar, now, recovering=True)
        with self.store.db:
            self.state["gap"] = False
            self.emit(
                "DATA_RESUMED",
                f"resumed|{self.state['gap_number']}",
                timestamp=now,
                continuity_verified=True,
                review_required=True,
                notify=True,
            )
            self.checkpoint()

    def close_position(self, key, account, bar, fill):
        ref, reason, timing = fill
        scenario = key.split("|")[1]
        costs = self.costs[scenario]
        p = account["position"]
        q, entry = p["quantity"], p["price"]
        exit_price = costs.price(ref, 1)
        exit_fee = q * exit_price * costs.fee
        execution_gross = q * (entry - exit_price)
        net = execution_gross - p["entry_fee"] - exit_fee
        c = self.cost_configs[scenario]
        slippage = q * (p["reference"] + ref) * c.slippage_pct / 100
        spread = q * (p["reference"] + ref) * c.spread_pct / 200
        account["balance"] += execution_gross - exit_fee
        account["realized_net"] += net
        account["fees_paid"] += exit_fee
        account["closed_trades"] += 1
        eligible = p["coverage"] == "CONTINUOUS"
        account["eligible_closed_trades"] += int(eligible)
        self.emit(
            "SHADOW_EXIT",
            f"exit|{p['id']}",
            timestamp=bar.close_time,
            candidate=key.split("|")[0],
            scenario=scenario,
            position_id=p["id"],
            entry_time=p["close"],
            exit_bar_open=bar.timestamp,
            exit_time=bar.timestamp if timing == "open" else None,
            exit_timing=timing,
            entry_price=entry,
            exit_price=exit_price,
            stop=p["stop"],
            target=p["target"],
            quantity=q,
            entry_fee=p["entry_fee"],
            exit_fee=exit_fee,
            price_pnl_gross=q * (p["reference"] - ref),
            execution_pnl_gross=execution_gross,
            slippage=slippage,
            spread=spread,
            net_pnl=net,
            reason=reason,
            coverage=p["coverage"],
            evidence_eligible=eligible,
            notify=True,
        )
        account["position"] = None

    def closed(self, bar, now, recovering=False):
        validate_bar(bar, self.instrument, now)
        rows = self.book.bars.get((self.instrument, "1h"), {})
        if bar.timestamp in rows:
            self.book.add(bar)  # Reject revisions even for a duplicate already processed.
            return False
        if self.state["gap"] and not recovering:
            raise DataGap("Unresolved continuity incident")
        with self.store.db:
            try:
                self.book.add(bar)
            except DataGap:
                raise
            for candidate in list(self.state["pending"]):
                if utc(self.state["pending"][candidate]["close"]) <= bar.timestamp:
                    self.missed(candidate, "next_open_not_captured", now)
            self.emit(
                "MARKET_BAR_CLOSED", bar.key, **bar.row(), observed_at=now, recovering=recovering
            )
            for key, account in self.state["accounts"].items():
                p = account["position"]
                if p:
                    fill = protective_fill(
                        SimpleNamespace(**bar.row()),
                        SizedEntry(
                            p["price"],
                            p["quantity"],
                            p["stop"],
                            p["target"],
                            p["entry_fee"],
                            p["risk_budget"],
                            p["expected_stop_loss"],
                        ),
                        -1,
                    )
                    if fill:
                        self.close_position(key, account, bar, fill)
                p = account["position"]
                equity = account["balance"] + (p["quantity"] * (p["price"] - bar.close) if p else 0)
                if p:
                    model = self.costs[key.split("|")[1]]
                    hypothetical_exit = model.price(bar.close, 1)
                    p.update(
                        mark_price=bar.close,
                        as_of=bar.close_time.isoformat(),
                        unrealized_pnl_gross=p["quantity"] * (p["price"] - bar.close),
                        unrealized_pnl_net_estimate=p["quantity"] * (p["price"] - hypothetical_exit)
                        - p["entry_fee"]
                        - p["quantity"] * hypothetical_exit * model.fee,
                    )
                if not isfinite(equity):
                    raise ValueError("Nonfinite equity")
                account["equity"] = equity
                account["peak"] = max(account["peak"], equity)
                dd = (1 - equity / account["peak"]) * 100
                account["max_drawdown_pct"] = max(account["max_drawdown_pct"], dd)
                self.emit(
                    "EQUITY",
                    f"equity|{key}|{bar.timestamp}",
                    timestamp=bar.close_time,
                    account=key,
                    equity=equity,
                    drawdown_pct=dd,
                    recovering=recovering,
                )
                if dd > 15 and not self.state["paused"]:
                    self.state["paused"] = True
                    self.emit(
                        "DRAWDOWN_LIMIT_BREACH",
                        "dd_limit",
                        account=key,
                        timestamp=bar.close_time,
                        drawdown_pct=dd,
                        notify=True,
                    )
            self.state["last_closed"] = bar.timestamp.isoformat()
            eligible = (
                not recovering
                and not self.state["paused"]
                and bar.close_time > self.started
                and bar.close_time >= self.nominal
            )
            if eligible:
                timely = utc(now) - bar.close_time <= pd.Timedelta(seconds=90)
                if timely and self.state["effective_start"] is None:
                    self.state["effective_start"] = bar.close_time.isoformat()
                    self.emit(
                        "PROSPECTIVE_START",
                        "effective_start",
                        timestamp=bar.close_time,
                        nominal_start=self.nominal,
                        actual_start=bar.close_time,
                    )
                generated = []
                frame = self.book.frame(self.instrument, "1h")
                for name, (strategy, _) in self.candidates.items():
                    features = strategy.prepare_features(frame)
                    if strategy.generate_short_entries(features)[-1]:
                        f = features.iloc[-1]
                        pending = dict(
                            close=bar.close_time.isoformat(),
                            distance=float(f.atr) * 2,
                            atr=float(f.atr),
                            ema=float(f.trend_ema),
                            channel=float(f.breakout_low),
                            expansion=float(f.atr_expansion),
                        )
                        self.state["pending"][name] = pending
                        self.emit(
                            "SIGNAL_GENERATED",
                            f"signal|{name}|{bar.close_time}",
                            candidate=name,
                            timestamp=bar.close_time,
                            parameters=strategy.parameters.model_dump(),
                            version=strategy.version,
                            **pending,
                            notify=False,
                        )
                        if timely:
                            generated.append(name)
                        else:
                            self.missed(name, "signal_arrived_after_next_open_deadline", now)
                if generated:
                    self.emit(
                        "SIGNAL_GROUP",
                        f"signals|{bar.close_time}",
                        timestamp=bar.close_time,
                        candidates=generated,
                        notify=True,
                    )
            self.checkpoint()
        return True

    def opening(self, timestamp, price, observed_at, *, volume):
        """Only current trade-candle OPEN, observed promptly; never a ticker or backfill."""
        stamp, now = utc(timestamp), utc(observed_at)
        if (
            stamp != stamp.floor("h")
            or now < stamp
            or now >= stamp + pd.Timedelta(hours=1)
            or not isfinite(price)
            or price <= 0
            or not isfinite(volume)
            or volume <= 0
        ):
            raise ValueError("Invalid observed next-open reference")
        if self.state["gap"] or self.state["paused"]:
            return
        if stamp != utc(self.state["last_closed"]) + pd.Timedelta(hours=1):
            raise DataGap("Opening has no preceding confirmed signal context")
        with self.store.db:
            entries = []
            for candidate in list(self.state["pending"]):
                pending = self.state["pending"][candidate]
                signal = utc(pending["close"])
                if stamp != signal or now - stamp > pd.Timedelta(seconds=90):
                    self.missed(candidate, "late_or_missing_next_open", now)
                    continue
                for scenario, costs in self.costs.items():
                    key = f"{candidate}|{scenario}"
                    account = self.state["accounts"][key]
                    if account["position"]:
                        continue
                    sized = size_entry(
                        account["balance"],
                        price,
                        pending["distance"],
                        -1,
                        self.candidates[candidate][1],
                        self.execution,
                        costs,
                    )
                    if isinstance(sized, str):
                        self.emit(
                            "SIGNAL_REJECTED",
                            f"reject|{key}|{stamp}",
                            timestamp=now,
                            account=key,
                            reason=sized,
                        )
                        continue
                    p = asdict(sized) | dict(
                        id=identity(self.store.stream, key, stamp),
                        reference=price,
                        close=stamp.isoformat(),
                        coverage="CONTINUOUS",
                        as_of=now.isoformat(),
                        mark_price=price,
                        unrealized_pnl_gross=sized.quantity * (sized.price - price),
                        unrealized_pnl_net_estimate=sized.quantity
                        * (sized.price - costs.price(price, 1))
                        - sized.entry_fee
                        - sized.quantity * costs.price(price, 1) * costs.fee,
                    )
                    account["balance"] -= sized.entry_fee
                    account["fees_paid"] += sized.entry_fee
                    account["position"] = p
                    account["equity"] = account["balance"] + sized.quantity * (sized.price - price)
                    payload = dict(
                        candidate=candidate,
                        scenario=scenario,
                        timestamp=stamp,
                        observed_at=now,
                        latency_seconds=(now - stamp).total_seconds(),
                        notional=sized.quantity * sized.price,
                        costs=self.cost_configs[scenario].model_dump(),
                        **asdict(sized),
                        contracts=str(
                            sized.quantity
                            / float(self.store.metadata["config"]["instrument"]["contract_size"])
                        ),
                    )
                    self.emit(
                        "ORDER_INTENT_CREATED", f"intent|{key}|{stamp}", **payload, notify=False
                    )
                    self.emit(
                        "SHADOW_ENTRY",
                        f"entry|{key}|{stamp}",
                        **payload,
                        entry_reference=price,
                        notify=False,
                    )
                    entries.append(payload)
                del self.state["pending"][candidate]
            if entries:
                self.emit(
                    "SHADOW_ENTRY_GROUP",
                    f"entries|{stamp}",
                    timestamp=stamp,
                    entries=entries,
                    notify=True,
                )
            self.checkpoint()


def inspect(db_path: Path, session=None):
    """Snapshot only; does not recreate accounting, write reports or acquire runner locks."""
    with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as db:
        db.execute("BEGIN")
        sessions = [
            json.loads(r[0]) for r in db.execute("SELECT data FROM sessions ORDER BY rowid")
        ]
        if session is None:
            return {
                "sessions": [
                    {k: s.get(k) for k in ("session_id", "start", "status", "stream_id")}
                    for s in sessions
                ]
            }
        chosen = next((s for s in sessions if s["session_id"] == session), None)
        if not chosen:
            raise ValueError("Unknown Donchian session")
        state = json.loads(
            db.execute(
                "SELECT data FROM checkpoints WHERE stream=?", (chosen["stream_id"],)
            ).fetchone()[0]
        )
        events = [
            json.loads(r[0])
            for r in db.execute(
                "SELECT data FROM events WHERE stream=? ORDER BY rowid", (chosen["stream_id"],)
            )
        ]
        return dict(
            session=session,
            checkpoint_scope="continuous stream across resume segments",
            nominal_start=chosen["config"]["nominal_start"],
            state=state | {"candles": len(state["candles"])},
            recent_events=events[-25:],
            disclaimer=DISCLAIMER,
        )
