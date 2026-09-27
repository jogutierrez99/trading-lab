"""Causal signal lifecycle; separate frozen origins from execution decisions."""

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import Field, model_validator

from quant_lab.config import StrictModel, load_yaml


class Guards(StrictModel):
    cooldown_hours: int = Field(default=1, ge=0)
    extension_atr: float = Field(default=1.5, gt=0)
    validity_quarters: int = Field(default=4, ge=1)
    dynamic_spread_enabled: bool = False
    max_spread_pct: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def spread_contract(self):
        if self.dynamic_spread_enabled and self.max_spread_pct is None:
            raise ValueError("Dynamic spread needs an explicit threshold and observed quotes")
        return self


def guards():
    return load_yaml(Path("configs/profiles/execution_refinement.yaml"), Guards)


@dataclass(frozen=True)
class FrozenSignal:
    signal_id: str
    direction: str
    signal_timestamp: pd.Timestamp
    signal_price: float
    signal_reference_level: float
    regime_state: str
    expiry_timestamp: pd.Timestamp
    atr: float


class ExecutionPolicy:
    """Only opening price and already-closed features enter this state machine.

    A V2.1 opportunity is a distinct valid hourly close, not an indicator episode.
    V4.1 evaluates four subsequent quarter closes, including the expiry boundary.
    Terminal signals never become active again. No queue survives an hourly expiry.
    """

    def __init__(self, features, start, end, asset, family, version, config=None, spreads=None):
        self.features = features.to_dict("index")
        self.start, self.end = start, end
        self.asset, self.family, self.version = asset, family, version
        self.config = config or guards()
        if self.config.dynamic_spread_enabled and spreads is None:
            raise ValueError("No observed dynamic spread data supplied")
        self.spreads = spreads or {}
        self.active = None
        self.records = {}
        self.events = []
        self.last_exit = None
        self.candidate = None
        self.position_signal = None

    def log(self, time, signal, action, reason, **extra):
        self.events.append(
            {
                "time": time,
                "signal_id": signal.signal_id,
                "action": action,
                "reason": reason,
                **extra,
            }
        )

    def terminate(self, time, reason, status="invalidated"):
        signal = self.active
        if signal is None:
            return
        record = self.records[signal.signal_id]
        if record["status"] == "pending":
            record.update(status=status, invalidated=status == "invalidated", expiry_reason=reason)
            self.log(time, signal, status.upper(), reason)
        self.active = None

    def create(self, time, row):
        raw = f"{self.asset}|{self.family}|{self.version}|long|{time.isoformat()}"
        signal = FrozenSignal(
            hashlib.sha256(raw.encode()).hexdigest()[:24],
            "long",
            time,
            float(row["origin_price"]),
            float(row["origin_reference"]),
            "LONG",
            time + pd.Timedelta(minutes=15 * self.config.validity_quarters),
            float(row["origin_atr"]),
        )
        self.active = signal
        self.records[signal.signal_id] = asdict(signal) | {
            "status": "pending",
            "consumed": False,
            "invalidated": False,
            "expiry_reason": None,
            "entry_time": None,
            "signal_age": None,
            "time_to_entry": None,
            "entry_distance_atr": None,
        }
        self.log(time, signal, "GENERATE", "closed_1h_signal")

    def attempt(self, time, opening, has_position, row):
        signal = self.active
        if signal is None:
            return None
        state = self.records[signal.signal_id]
        trigger = self.version == "V2.1" or (
            bool(row["execution_trigger"])
            and pd.notna(row["touch_open"])
            and row["touch_open"] >= signal.signal_timestamp
        )
        if state["consumed"]:
            if trigger:
                self.log(time, signal, "BLOCK", "consumed")
            return None
        if not bool(row["regime_valid"]):
            self.terminate(time, "regime_changed")
            return None
        if not bool(row["setup_valid"]):
            self.terminate(time, "setup_invalid")
            return None
        distance = abs(opening - signal.signal_price) / signal.atr
        if distance > self.config.extension_atr:
            self.log(time, signal, "BLOCK", "extension", distance_atr=distance)
            self.terminate(time, "extension")
            return None
        if not trigger:
            return None
        reason = None
        if has_position:
            reason = "position_open"
        elif self.last_exit is not None and time < self.last_exit + pd.Timedelta(
            hours=self.config.cooldown_hours
        ):
            reason = "cooldown"
        elif self.config.dynamic_spread_enabled:
            spread = self.spreads.get(time)
            if spread is None or not np.isfinite(spread) or spread > self.config.max_spread_pct:
                reason = "spread_unavailable_or_high"
        if reason:
            self.log(time, signal, "BLOCK", reason)
            if self.version == "V2.1":
                self.terminate(time, reason)
            return None
        self.candidate = signal
        self.log(time, signal, "ATTEMPT", "eligible", distance_atr=distance)
        return {"le": True, "se": False, "lx": False, "sx": False, "distance": 2 * signal.atr}

    def decision(self, time, opening, has_position):
        self.candidate = None
        if time <= self.start or time >= self.end:
            return None
        row = self.features.get(time)
        if row is None:
            return None
        if (
            self.version == "V2.1"
            and self.active is not None
            and time > self.active.signal_timestamp
        ):
            self.terminate(time, "execution_not_filled")
        if self.active is not None and time > self.active.expiry_timestamp:
            self.terminate(time, "validity_elapsed", "expired")
        result = self.attempt(time, opening, has_position, row)
        if self.active is not None and time == self.active.expiry_timestamp and result is None:
            self.terminate(time, "validity_elapsed", "expired")
        # At the shared boundary the older signal has priority; a fresh opportunity
        # is still recorded, but cannot displace an accepted older execution.
        if bool(row["new_signal"]):
            if result is not None:
                previous = self.active
                self.create(time, row)
                self.terminate(time, "older_signal_priority")
                self.active = previous
            else:
                if self.active is not None:
                    self.terminate(time, "replaced_at_hourly_boundary", "expired")
                self.create(time, row)
                result = self.attempt(time, opening, has_position, row)
        return result

    def on_entry(self, time, price):
        signal = self.candidate
        if signal is None:
            raise AssertionError("Fill without an originating signal")
        record = self.records[signal.signal_id]
        if record["consumed"]:
            raise AssertionError("Signal filled more than once")
        age = (time - signal.signal_timestamp).total_seconds() / 3600
        record.update(
            status="consumed",
            consumed=True,
            entry_time=time,
            signal_age=age,
            time_to_entry=age,
            entry_distance_atr=abs(price - signal.signal_price) / signal.atr,
        )
        self.log(time, signal, "ENTER", "filled", entry_price=price)
        self.position_signal = signal

    def on_exit(self, time):
        self.last_exit = time
        if self.position_signal is not None:
            self.log(time, self.position_signal, "EXIT", "position_closed")
            self.position_signal = None

    def finalize(self, time, reason):
        self.terminate(time, reason, "expired")


def diagnostics(policies):
    records = [r for p in policies for r in p.records.values()]
    events = [e for p in policies for e in p.events]
    executed = [r for r in records if r["consumed"]]

    def count(reason):
        return sum(e["action"] == "BLOCK" and e["reason"] in reason for e in events)

    ages = [r["signal_age"] for r in executed]
    distances = [r["entry_distance_atr"] for r in executed]
    return (
        {
            "signals_generated": len(records),
            "signals_executed": len(executed),
            "signals_consumed": len(executed),
            "signals_expired": sum(r["status"] == "expired" for r in records),
            "signals_invalidated": sum(r["invalidated"] for r in records),
            "duplicate_entries_prevented": count({"consumed", "position_open"}),
            "cooldown_entries_blocked": count({"cooldown"}),
            "extension_entries_blocked": count({"extension"}),
            "average_signal_age": float(np.mean(ages)) if ages else None,
            "median_signal_age": float(np.median(ages)) if ages else None,
            "average_entry_distance_atr": float(np.mean(distances)) if distances else None,
            "average_time_to_entry": float(np.mean(ages)) if ages else None,
            "trades_per_signal": len(executed) / len(records) if records else None,
        },
        records,
        events,
    )
