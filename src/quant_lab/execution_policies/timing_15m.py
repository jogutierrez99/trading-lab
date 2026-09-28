"""Single frozen 60-minute policy per original hourly opportunity."""

from dataclasses import asdict, dataclass
from hashlib import sha256
from math import isfinite

import pandas as pd

STEP = pd.Timedelta(minutes=15)


@dataclass(frozen=True)
class Opportunity:
    signal_id: str
    asset: str
    family: str
    architecture: str
    direction: str
    signal_close_time: pd.Timestamp
    baseline_entry_time: pd.Timestamp
    signal_reference_price: float
    signal_atr: float
    regime_state: str
    setup_state: str
    expiry_time: pd.Timestamp
    structure_level: float


def opportunity(asset, family, architecture, time, row):
    identity = f"{asset}|{family}|{architecture}|long|{time.isoformat()}"
    return Opportunity(
        sha256(identity.encode()).hexdigest()[:24],
        asset,
        family,
        architecture,
        "long",
        time,
        time,
        float(row.origin_price),
        float(row.origin_atr),
        "NOT_APPLICABLE" if architecture == "V1" else "LONG",
        "ORIGINAL_HOURLY_SIGNAL",
        time + 4 * STEP,
        float(row.structure_level),
    )


def record_for(signal):
    return asdict(signal) | {
        "status": "CREATED",
        "entry_time": None,
        "entry_price": None,
        "bars_waited_15m": None,
        "minutes_waited": None,
        "distance_from_signal_atr": None,
        "reason": None,
    }


class TimingPolicy:
    def __init__(self, features, left, right, asset, family, architecture):
        self.rows = features.loc[(features.index >= left) & (features.index < right)].to_dict(
            "index"
        )
        self.left, self.right = left, right
        self.asset, self.family, self.architecture = asset, family, architecture
        self.active = None
        self.attempt = None
        self.touch = None
        self.records = []
        self.events = []
        self.last_time = None

    def transition(self, record, time, status, reason=None):
        record.update(status=status, reason=reason)
        self.events.append(
            {
                "signal_id": record["signal_id"],
                "time": time,
                "status": status,
                "reason": reason,
            }
        )

    def terminate(self, time, status, reason):
        if self.active is not None:
            self.transition(self.active[1], time, status, reason)
        self.active, self.touch, self.attempt = None, None, None

    def decision(self, time, opening_price, has_position):
        if self.attempt is not None:
            self.terminate(time, "INVALIDATED", "entry_rejected_by_engine")
        if self.last_time is not None and time - self.last_time != STEP:
            self.terminate(time, "INVALIDATED", "gap")
        self.last_time = time
        if time not in self.rows or not self.left < time < self.right:
            return None
        row = pd.Series(self.rows[time])
        decision = None
        if self.active is not None:
            signal, record = self.active
            if time > signal.expiry_time:
                self.terminate(time, "EXPIRED", "expiry")
            elif has_position:
                self.terminate(time, "INVALIDATED", "position_open")
            elif not row.regime_valid:
                self.terminate(time, "INVALIDATED", "original_regime")
            elif not row.structure_valid or row.close <= signal.structure_level:
                self.terminate(time, "INVALIDATED", "original_structure")
            elif (
                max(
                    abs(row.close - signal.signal_reference_price),
                    abs(opening_price - signal.signal_reference_price),
                )
                > 1.5 * signal.signal_atr
            ):
                self.terminate(time, "INVALIDATED", "extension")
            else:
                age = int((time - signal.signal_close_time) / STEP)
                trigger = False
                if self.family == "supertrend_pullback":
                    trigger = self.touch is not None and time > self.touch and row.recovery
                    if row.touch:
                        self.touch = time
                else:
                    # Three completed post-origin consolidation candles, then breakout candle.
                    trigger = age >= 4 and row.consolidation and row.breakout
                if trigger and age >= 1:
                    self.attempt = record
                    decision = {
                        "le": True,
                        "se": False,
                        "lx": False,
                        "sx": False,
                        "distance": 2 * signal.signal_atr,
                    }
                elif time == signal.expiry_time:
                    self.terminate(time, "EXPIRED", "expiry")
        if row.new_signal:
            signal = opportunity(self.asset, self.family, self.architecture, time, row)
            record = record_for(signal)
            self.records.append(record)
            self.transition(record, time, "CREATED")
            if has_position or self.active is not None:
                self.transition(record, time, "INVALIDATED", "position_or_pending_signal")
            elif not isfinite(signal.signal_atr) or signal.signal_atr <= 0:
                self.transition(record, time, "INVALIDATED", "invalid_original_atr")
            else:
                self.active = signal, record
                self.touch = None
                self.transition(record, time, "WAITING")
        return decision

    def on_entry(self, time, price):
        if self.attempt is None or self.active is None:
            raise AssertionError("Entry without an original signal")
        signal, record = self.active
        record.update(
            entry_time=time,
            entry_price=price,
            bars_waited_15m=int((time - signal.signal_close_time) / STEP),
            minutes_waited=(time - signal.signal_close_time).total_seconds() / 60,
            distance_from_signal_atr=abs(price - signal.signal_reference_price) / signal.signal_atr,
        )
        self.transition(record, time, "ENTERED")
        self.transition(record, time, "CONSUMED")
        self.active, self.attempt, self.touch = None, None, None

    def on_exit(self, time):
        pass

    def finalize(self, time, reason):
        self.terminate(time, "INVALIDATED", reason)


def timing_metrics(records, baseline_entries=None):
    baseline_entries = baseline_entries or {}
    entered = [r for r in records if r["status"] == "CONSUMED"]
    values = {
        "signals_created": len(records),
        "signals_entered": len(entered),
        "signals_expired": sum(r["status"] == "EXPIRED" for r in records),
        "signals_invalidated": sum(r["status"] == "INVALIDATED" for r in records),
        "signals_blocked_extension": sum(r["reason"] == "extension" for r in records),
        "signal_execution_rate": len(entered) / len(records) if records else None,
    }
    improvement = [
        100
        * (baseline_entries[r["signal_id"]] - r["entry_price"])
        / baseline_entries[r["signal_id"]]
        for r in entered
        if r["signal_id"] in baseline_entries
    ]
    for name, data in (
        ("wait_minutes", [r["minutes_waited"] for r in entered]),
        ("entry_distance_atr", [r["distance_from_signal_atr"] for r in entered]),
        ("fill_improvement_pct", improvement),
    ):
        series = pd.Series(data, dtype=float)
        values["average_" + name] = float(series.mean()) if len(series) else None
        values["median_" + name] = float(series.median()) if len(series) else None
    values["paired_fills"] = len(improvement)
    return values
