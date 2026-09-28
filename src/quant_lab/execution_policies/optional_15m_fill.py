"""Causal optional fill: improve now, otherwise market fallback at the deadline.

Only entry-time facts from the causal shadow baseline enter this policy. No
baseline exit, future PnL or future min/max is available to decision().
"""

from dataclasses import asdict, dataclass
from hashlib import sha256
from types import SimpleNamespace

import pandas as pd

from quant_lab.risk import CostModel

STEP = pd.Timedelta(minutes=15)
WINDOW = 4 * STEP


@dataclass(frozen=True)
class BaselineEntry:
    baseline_trade_id: str
    signal_id: str
    baseline_signal_time: pd.Timestamp
    baseline_entry_time: pd.Timestamp
    baseline_entry_price: float
    signal_atr: float
    stop_distance: float
    structure_level: float
    retest_level: float


def entry_identity(case, partition, scenario, time):
    signal = sha256(("|".join(case) + "|long|" + time.isoformat()).encode()).hexdigest()[:24]
    trade = sha256(f"{signal}|{partition}|{scenario}".encode()).hexdigest()[:24]
    return signal, trade


def pair_record(entry):
    return asdict(entry) | {
        "status": "WAITING",
        "optimized_entry_used": False,
        "optimized_entry_time": None,
        "optimized_entry_price": None,
        "experimental_entry_time": None,
        "experimental_entry_price": None,
        "fallback_used": False,
        "fallback_reason": None,
        "non_execution_reason": None,
        "fill_improvement_abs": None,
        "fill_improvement_pct": None,
        "fill_improvement_atr": None,
        "wait_minutes": None,
        "attempts": 0,
    }


class OptionalFillPolicy:
    def __init__(self, features, entries, left, right, family, costs):
        self.rows = features.loc[(features.index >= left) & (features.index < right)].to_dict(
            "index"
        )
        self.entries = {
            e.baseline_entry_time: e for e in entries if left < e.baseline_entry_time < right
        }
        if len(self.entries) != sum(left < e.baseline_entry_time < right for e in entries):
            raise ValueError("Duplicate baseline entry time")
        self.left, self.right, self.family = left, right, family
        self.costs = CostModel.from_config(costs)
        self.pending = []
        self.records = []
        self.attempt = None
        self.last_time = None

    def reject_attempt(self, time):
        if self.attempt is not None:
            item, _optimized = self.attempt
            self.attempt = None
            # Retry at a later available open through the deadline, never duplicate a fill.
            if time > item["deadline"]:
                item["record"].update(
                    status="NOT_EXECUTED", non_execution_reason="engine_risk_rejection"
                )
                self.pending.remove(item)

    def trigger(self, item, row, time):
        entry = item["entry"]
        if row.close <= entry.structure_level:
            return False  # only disables optimization; never cancels fallback
        age = int((time - entry.baseline_entry_time) / STEP)
        if self.family in {"ema_adx", "trend_pullback"}:
            return age >= 1 and row.low <= row.ema20 <= row.high and row.close > row.open
        if self.family == "supertrend_pullback":
            trigger = item["touched"] is not None and time > item["touched"] and row.recovery
            if row.low <= row.ema20 <= row.high:
                item["touched"] = time
            return trigger
        if self.family == "keltner_breakout":
            return (
                age >= 1
                and row.low <= entry.retest_level <= row.high
                and row.close > entry.retest_level
            )
        if self.family == "roc_momentum":
            return age >= 4 and row.consolidation and row.breakout
        raise ValueError(f"Unsupported fill family: {self.family}")

    def decision(self, time, opening_price, has_position):
        self.reject_attempt(time)
        if self.last_time is not None and time - self.last_time != STEP:
            for item in self.pending:
                item["record"].update(status="NOT_EXECUTED", non_execution_reason="unexpected_gap")
            self.pending.clear()
        self.last_time = time
        if not self.left < time < self.right:
            return None
        if time in self.entries:
            entry = self.entries.pop(time)
            record = pair_record(entry)
            self.records.append(record)
            self.pending.append(
                {
                    "entry": entry,
                    "record": record,
                    "touched": None,
                    "deadline": min(time + WINDOW, self.right - STEP),
                }
            )
        row = SimpleNamespace(**self.rows[time]) if time in self.rows else None
        for item in list(self.pending):
            entry, record = item["entry"], item["record"]
            if time > item["deadline"]:
                record.update(
                    status="NOT_EXECUTED", non_execution_reason="position_capacity_at_deadline"
                )
                self.pending.remove(item)
                continue
            eligible = time > entry.baseline_entry_time and row is not None
            trigger = self.trigger(item, row, time) if eligible else False
            better = (
                self.costs.price(opening_price, 1) < entry.baseline_entry_price
                and opening_price > entry.structure_level
            )
            optimized = bool(trigger and better)
            due = time == item["deadline"]
            if has_position:
                if due:
                    record.update(
                        status="NOT_EXECUTED", non_execution_reason="position_capacity_at_deadline"
                    )
                    self.pending.remove(item)
                continue
            if optimized or due:
                record["attempts"] += 1
                record["fallback_reason"] = (
                    None
                    if optimized
                    else (
                        "segment_or_window_boundary"
                        if item["deadline"] < entry.baseline_entry_time + WINDOW
                        else "deadline_market_fallback"
                    )
                )
                self.attempt = item, optimized
                return {
                    "le": True,
                    "se": False,
                    "lx": False,
                    "sx": False,
                    "distance": entry.stop_distance,
                }
        return None

    def on_entry(self, time, price):
        if self.attempt is None:
            raise AssertionError("Entry without baseline opportunity")
        item, optimized = self.attempt
        entry, record = item["entry"], item["record"]
        if optimized and not price < entry.baseline_entry_price:
            raise AssertionError("Optimized fill must strictly improve baseline after costs")
        improvement = entry.baseline_entry_price - price
        record.update(
            status="ENTERED",
            optimized_entry_used=optimized,
            fallback_used=not optimized,
            experimental_entry_time=time,
            experimental_entry_price=price,
            optimized_entry_time=time if optimized else None,
            optimized_entry_price=price if optimized else None,
            fill_improvement_abs=improvement,
            fill_improvement_pct=100 * improvement / entry.baseline_entry_price,
            fill_improvement_atr=improvement / entry.signal_atr,
            wait_minutes=(time - entry.baseline_entry_time).total_seconds() / 60,
        )
        self.pending.remove(item)
        self.attempt = None

    def on_exit(self, time):
        pass

    def finalize(self, time, reason):
        self.reject_attempt(time)
        for item in self.pending:
            item["record"].update(status="NOT_EXECUTED", non_execution_reason=reason)
        self.pending.clear()


def fill_metrics(records):
    entered = [r for r in records if r["status"] == "ENTERED"]
    optimized = [r for r in entered if r["optimized_entry_used"]]
    fallback = [r for r in entered if r["fallback_used"]]
    total = len(records)
    retention = len(entered) / total if total else None
    result = {
        "signals_total": total,
        "optimized_entries": len(optimized),
        "fallback_entries": len(fallback),
        "unexecuted_entries": total - len(entered),
        "optimization_rate": len(optimized) / total if total else None,
        "fallback_rate": len(fallback) / total if total else None,
        "trade_retention_rate": retention,
        "retention_warning": retention is not None and retention < 0.98,
        "retention_explanation_required": retention is not None and retention < 0.95,
        "number_of_worse_fills": sum(r["fill_improvement_abs"] < 0 for r in entered),
        "number_of_worse_optimized_fills": sum(r["fill_improvement_abs"] <= 0 for r in optimized),
        "number_of_worse_fallback_fills": sum(r["fill_improvement_abs"] < 0 for r in fallback),
        "unexecuted_reasons": "; ".join(
            sorted({r["non_execution_reason"] for r in records if r["status"] != "ENTERED"})
        ),
    }
    for name, field in (
        ("wait_minutes", "wait_minutes"),
        ("fill_improvement_pct", "fill_improvement_pct"),
        ("fill_improvement_atr", "fill_improvement_atr"),
    ):
        values = pd.Series([r[field] for r in entered], dtype=float)
        result["average_" + name] = float(values.mean()) if len(values) else None
        result["median_" + name] = float(values.median()) if len(values) else None
    if result["unexecuted_entries"] and not result["unexecuted_reasons"]:
        raise AssertionError("Every missing trade requires an explanation")
    return result
