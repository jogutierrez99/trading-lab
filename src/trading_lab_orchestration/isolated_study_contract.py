"""Sealed StudyBackend input and bounded, data-only output."""

import json
import re
from datetime import datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from math import isclose
from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, model_validator

from .contracts import Model, canonical, digest

Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Key = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")]
Positive = Annotated[FiniteFloat, Field(gt=0)]
Nonnegative = Annotated[FiniteFloat, Field(ge=0)]
Percent = Annotated[FiniteFloat, Field(ge=0, le=100)]
MAX_WIRE = 512 * 1024
IMAGE = "sha256:539a1a6c2f1669b6c36612417f9cf70fe28e822095433d8a1453e706396b5f2e"
BASE = "5cef79b45780c9a0e9964b01b2fa46d9531ae18a"
ENGINE = "StudyBackend v1"
DATA = "inputs/synthetic.json"
PILOT_STRATEGY = "btc_spot_sma50_sma200_1h_pilot_v1"
PILOT_DATASET = "2322037acf66bdb51b4af3bc76c278d0dce85d2bc5bf2d0e8cd97e86d6eac04b"
PILOT_PARQUET = "ffcbcb8f8daccaf1f7d9d8c2a1d43075ed1a64e0b6629f30d5a31a79937db0c7"
SCHEDULE = {
    "train": ("2022-02-01", "2022-04-01"),
    "validation": ("2022-04-01", "2022-05-01"),
    "test_retrospective": ("2022-05-01", "2022-06-01"),
}
DEPENDENCIES = {
    "numpy": "2.3.5",
    "pandas": "2.3.3",
    "pyarrow": "23.0.1",
    "pydantic": "2.14.3",
    "PyYAML": "6.0.3",
}


class Costs(Model):
    trading_fee_pct: Percent
    slippage_pct: Percent
    spread_pct: Percent


class Risk(Model):
    initial_cash: Positive
    risk_per_trade_pct: Percent
    max_position_pct: Percent
    max_exposure_pct: Percent
    atr_period: int = Field(ge=1, le=1000)
    atr_multiplier: Positive
    risk_reward: Positive
    quantity_step: Positive
    min_quantity: Positive
    min_notional: Nonnegative
    mode: Literal["LONG_ONLY"] = "LONG_ONLY"
    market_mode: Literal["spot"] = "spot"
    timing: Literal["NEXT_OPEN"] = "NEXT_OPEN"
    sizing: Literal["stop_risk"] = "stop_risk"
    liquidate_at_end: Literal[True] = True
    trailing: Literal[False] = False
    time_stop: Literal[False] = False
    funding: Literal["NOT_APPLICABLE"] = "NOT_APPLICABLE"
    intrabar: Literal["STUDYBACKEND_V1_PROTECTIVE_FIRST"] = "STUDYBACKEND_V1_PROTECTIVE_FIRST"


class Limits(Model):
    max_cases: int = Field(ge=1, le=6)
    wall_seconds: int = Field(ge=1, le=120)
    cpu: Literal[1] = 1
    memory_mib: Literal[768] = 768
    scratch_mib: Literal[32] = 32
    processes: Literal[64] = 64
    output_bytes: Literal[524288] = MAX_WIRE
    api_eur: Literal[0] = 0
    network: Literal["none"] = "none"
    allow_codex: Literal[False] = False
    allow_okx: Literal[False] = False
    allow_telegram: Literal[False] = False
    auto_retry: Literal[False] = False


def pilot_risk():
    return Risk(
        initial_cash=10000.0,
        risk_per_trade_pct=0.5,
        max_position_pct=100.0,
        max_exposure_pct=100.0,
        atr_period=14,
        atr_multiplier=2.0,
        risk_reward=2.0,
        quantity_step=0.000001,
        min_quantity=0.000001,
        min_notional=10.0,
    )


class Case(Model):
    id: Key
    segment: Literal["synthetic", "train", "validation", "test_retrospective"]
    scenario: Literal["base", "adverse"]
    start: datetime
    end: datetime
    warmup: int = Field(ge=1, le=1000)
    costs: Costs

    @property
    def bars(self):
        return int((self.end - self.start) / timedelta(hours=1))

    @model_validator(mode="after")
    def check_hourly_bounds(self):
        if (
            any(
                t.utcoffset() != timedelta(0) or t.minute or t.second or t.microsecond
                for t in (self.start, self.end)
            )
            or not 1 <= self.bars <= 1500
        ):
            raise ValueError("Invalid hourly UTC case window")
        return self


class Plan(Model):
    schema_version: Literal["1.0"] = "1.0"
    kind: Literal["SYNTHETIC_ACCEPTANCE", "HISTORICAL_PROPOSAL"]
    job_id: Key
    strategy: Key
    code_commit: Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
    symbol: Literal["BTCUSDT"] = "BTCUSDT"
    timeframe: Literal["1h"] = "1h"
    engine: Literal["StudyBackend v1"] = ENGINE
    engine_sha256: Hash
    protocol_sha256: Hash
    dependencies_sha256: Hash
    image: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    input_files: dict[str, Hash]
    dataset_id: Hash
    dataset_sha256: Hash
    parameters: dict[Key, int]
    issue_number: Literal[3] | None = None
    holdout: Literal["CONSUMED", "SYNTHETIC"] = "SYNTHETIC"
    risk: Risk
    limits: Limits
    cases: list[Case] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def check_scope(self):
        ids = {case.id for case in self.cases}
        pairs = {(case.segment, case.scenario) for case in self.cases}
        if (
            len(ids) != len(self.cases)
            or len(pairs) != len(ids)
            or len(ids) != self.limits.max_cases
        ):
            raise ValueError("Exact distinct case identities required")
        if (
            not self.input_files
            or len(self.input_files) > 512
            or any(not safe_member(name) for name in self.input_files)
        ):
            raise ValueError("Unexpected or unsafe input paths")
        if self.input_files.get("src/quant_lab/study_backend.py") != self.engine_sha256:
            raise ValueError("Engine hash does not match the archive")
        if self.dataset_sha256 not in self.input_files.values():
            raise ValueError("Dataset hash is not included in the input seal")
        if self.kind == "SYNTHETIC_ACCEPTANCE":
            if (
                self.holdout != "SYNTHETIC"
                or self.issue_number is not None
                or any(
                    case.segment != "synthetic" or case.start.year != 2000 or case.bars > 96
                    for case in self.cases
                )
            ):
                raise ValueError("Only independent synthetic cases are executable in 5.5A")
        else:
            self._check_pilot(pairs)
        return self

    def _check_pilot(self, pairs):
        if (
            self.issue_number != 3
            or self.holdout != "CONSUMED"
            or self.strategy != PILOT_STRATEGY
            or self.code_commit != BASE
            or self.image != IMAGE
            or self.dataset_id != PILOT_DATASET
            or self.dataset_sha256 != PILOT_PARQUET
            or self.parameters != {"fast_sma_period": 50, "slow_sma_period": 200}
            or pairs
            != {(segment, scenario) for segment in SCHEDULE for scenario in ("base", "adverse")}
        ):
            raise ValueError("Historical proposal must match the frozen Issue #3 scope")
        if self.risk != pilot_risk():
            raise ValueError("Historical proposal changed frozen risk")
        for case in self.cases:
            start, end = SCHEDULE[case.segment]
            multiplier = 1 if case.scenario == "base" else 2
            costs = Costs(
                trading_fee_pct=0.10 * multiplier,
                slippage_pct=0.03 * multiplier,
                spread_pct=0.02 * multiplier,
            )
            if (
                case.start != datetime.fromisoformat(start + "T00:00:00Z")
                or case.end != datetime.fromisoformat(end + "T00:00:00Z")
                or case.warmup != 240
                or case.costs != costs
            ):
                raise ValueError("Historical proposal changed a frozen case")


def safe_member(name):
    return (
        all(re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}", part) for part in name.split("/"))
        and len(name) <= 240
    )


class TradeRecord(Model):
    side: Literal["long"]
    signal_close: datetime
    entry_time: datetime
    exit_bar_open: datetime
    exit_time: datetime | None
    exit_timing: Literal["open", "close", "intrabar"]
    entry_price: Positive
    exit_price: Positive
    quantity: Positive
    stop: Positive
    target: Positive
    entry_fee: Nonnegative
    exit_fee: Nonnegative
    net_pnl: FiniteFloat
    reason: Literal["signal", "end_of_study", "stop", "target", "stop_gap", "target_gap"]
    risk_budget: Positive
    expected_stop_loss: Positive
    entry_reference: Positive
    exit_reference: Positive
    slippage_cost: Nonnegative
    spread_cost: Nonnegative
    holding_bars: int = Field(ge=0, le=1500)


class RejectionRecord(Model):
    time: datetime
    reason: Annotated[str, Field(pattern=r"^[a-z_]{1,60}$")]


class Metrics(Model):
    closed_trades: int = Field(ge=0, le=1500)
    return_pct: FiniteFloat
    max_drawdown_pct: Percent
    expectancy: FiniteFloat | None
    profit_factor: Nonnegative | None
    win_rate_pct: Percent | None
    average_close_exposure_pct: Nonnegative
    fees_paid: Nonnegative
    realized_net_pnl: FiniteFloat
    slippage_cost_closed_trades: Nonnegative
    spread_cost_closed_trades: Nonnegative
    rejected_entries: int = Field(ge=0, le=1500)


class CaseResult(Model):
    id: Key
    segment: Literal["synthetic", "train", "validation", "test_retrospective"]
    scenario: Literal["base", "adverse"]
    costs: Costs
    metrics: Metrics
    trades: list[TradeRecord] = Field(max_length=1500)
    rejections: list[RejectionRecord] = Field(max_length=1500)
    open_position: None
    equity: list[Positive] = Field(min_length=2, max_length=1501)
    exposure: list[Nonnegative] = Field(min_length=2, max_length=1501)


class Result(Model):
    schema_version: Literal["1.1"] = "1.1"
    status: Literal["COMPLETE"]
    job_id: Key
    plan_sha256: Hash
    image: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    engine_sha256: Hash
    dataset_sha256: Hash
    dependencies_sha256: Hash
    files: dict[str, CaseResult]
    sha256: dict[str, Hash]


class HostProcess(Model):
    exit_code: int | None
    timed_out: bool
    duration_seconds: Nonnegative


class HostEnvironment(Model):
    image: Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]
    engine_sha256: Hash
    protocol_sha256: Hash


class Reception(Model):
    schema_version: Literal["1.2"]
    status: Literal["COMPLETE", "FAILED", "TIMED_OUT", "UNKNOWN"]
    job_id: Key
    plan_sha256: Hash
    started_at_utc: datetime
    ended_at_utc: datetime
    environment: HostEnvironment
    process: HostProcess | None = None
    cleanup_confirmed: Literal[True] | None = None
    output_sha256: Hash | None = None
    export: dict | None = None
    reason: str | None = None
    evidence_sha256: dict[str, Hash]

    @model_validator(mode="after")
    def check_state(self):
        if (
            self.started_at_utc.utcoffset() != timedelta(0)
            or self.ended_at_utc.utcoffset() != timedelta(0)
            or self.ended_at_utc < self.started_at_utc
        ):
            raise ValueError("Invalid reception timestamps")
        if self.status == "COMPLETE":
            if (
                not self.cleanup_confirmed
                or self.process is None
                or self.process.exit_code != 0
                or self.process.timed_out
                or self.export is None
                or self.output_sha256 is None
                or self.reason is not None
            ):
                raise ValueError("Completed reception requires a successful cleaned execution")
        elif self.export is not None or self.output_sha256 is not None:
            raise ValueError("A partial result cannot be published")
        elif self.status == "TIMED_OUT" and (
            not self.cleanup_confirmed or self.process is None or not self.process.timed_out
        ):
            raise ValueError("Timeout without confirmed cleanup is uncertain")
        return self


def _unique(pairs):
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise ValueError("Duplicate JSON key")
        obj[k] = v
    return obj


def _nonfinite(_):
    raise ValueError("Non-finite JSON")


def synthetic_fixture() -> bytes:
    closes = [100 + i % 3 / 4 for i in range(36)]
    closes[20:24] = [102, 104, 108, 112]
    candles = []
    for i, close in enumerate(closes):
        opening = 100 if i == 0 else closes[i - 1]
        low = min(opening, close) - (8 if i == 28 else 0.5)
        candles.append([opening, max(opening, close) + 0.5, low, close, 1])
    return canonical(
        {
            "start": "2000-01-01T00:00:00Z",
            "ohlcv": candles,
            "long_entries": [17, 26, 32],
            "long_exits": [34],
        }
    ).encode()


class SemanticInconsistency(ValueError):
    def __init__(self, detail):
        super().__init__(f"REJECTED_SEMANTIC_INCONSISTENCY: {detail}")


def decode_result(raw: bytes, plan: Plan) -> Result:
    if not 0 < len(raw) < plan.limits.output_bytes:
        raise ValueError("Export exceeds wire bounds")
    try:
        parsed = json.loads(raw, object_pairs_hook=_unique, parse_constant=_nonfinite)
        result = Result.model_validate_json(canonical(parsed))
    except RecursionError as exc:
        raise ValueError("Export JSON exceeds nesting bounds") from exc
    if (
        result.job_id != plan.job_id
        or result.plan_sha256 != digest(canonical(plan.model_dump(mode="json")))
        or any(
            getattr(result, key) != getattr(plan, key)
            for key in ("image", "engine_sha256", "dataset_sha256", "dependencies_sha256")
        )
    ):
        raise ValueError("Result does not belong to sealed plan")
    names = {case.id: f"cases/{case.id}.json" for case in plan.cases}
    if set(result.files) != set(names.values()) or set(result.sha256) != set(result.files):
        raise ValueError("Unexpected, missing or unsafe result paths")
    fixture_bytes = synthetic_fixture()
    if (
        plan.kind != "SYNTHETIC_ACCEPTANCE"
        or plan.input_files.get(DATA) != plan.dataset_sha256
        or digest(fixture_bytes.decode()) != plan.dataset_sha256
    ):
        raise ValueError("Result validation requires the sealed synthetic fixture")
    fixture = json.loads(fixture_bytes)
    for case in plan.cases:
        name = names[case.id]
        if digest(canonical(parsed["files"][name])) != result.sha256[name]:
            raise ValueError("Result member SHA-256 mismatch")
        _check_case(result.files[name], case, plan.risk, fixture)
    return result


def _equal(actual, expected):
    if expected is None:
        return actual is None
    return actual is not None and isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-8)


def _check_case(data, case, risk, fixture):
    if (data.id, data.segment, data.scenario, data.costs) != (
        case.id,
        case.segment,
        case.scenario,
        case.costs,
    ):
        raise ValueError("Case identity or costs changed")
    eq = data.equity
    if len(eq) != case.bars + 1 or len(eq) != len(data.exposure):
        raise ValueError("Equity length contradicts window")
    if not _equal(eq[0], risk.initial_cash) or data.exposure[0] or data.exposure[-1]:
        raise SemanticInconsistency("Invalid opening equity or closing liquidation")
    previous_exit = None
    hour = timedelta(hours=1)
    fee = case.costs.trading_fee_pct / 100
    slip = case.costs.slippage_pct / 100
    spread = case.costs.spread_pct / 200
    adverse = (case.costs.slippage_pct + case.costs.spread_pct / 2) / 100
    balance = risk.initial_cash
    bars = fixture["ohlcv"]
    first = datetime.fromisoformat(fixture["start"])
    offset = (case.start - first) // hour
    if offset < case.warmup or offset + case.bars > len(bars):
        raise ValueError("Window outside sealed synthetic fixture")
    for trade in data.trades:
        times = [trade.entry_time, trade.signal_close, trade.exit_bar_open]
        expected_exit = {"open": trade.exit_bar_open, "close": trade.exit_bar_open + hour}.get(
            trade.exit_timing
        )
        if (
            any(t.utcoffset() != timedelta(0) or (t - case.start) % hour for t in times)
            or not case.start < trade.entry_time <= trade.exit_bar_open < case.end
            or trade.signal_close != trade.entry_time
            or trade.exit_time != expected_exit
            or trade.exit_time is not None
            and trade.exit_time.utcoffset() != timedelta(0)
            or previous_exit is not None
            and trade.entry_time <= previous_exit
            or not trade.stop < trade.entry_price < trade.target
            or not _equal(
                trade.target - trade.entry_price,
                (trade.entry_price - trade.stop) * risk.risk_reward,
            )
            or trade.expected_stop_loss > trade.risk_budget + 1e-8
        ):
            raise SemanticInconsistency("Trades contradict chronology or risk controls")
        previous_exit = trade.exit_bar_open
        index = (trade.entry_time - first) // hour
        estimated_stop_fill = trade.stop * (1 - adverse)
        loss_per_unit = (
            trade.entry_price
            - estimated_stop_fill
            + fee * (trade.entry_price + estimated_stop_fill)
        )
        if balance <= 0 or loss_per_unit <= 0:
            raise SemanticInconsistency("Entry has no available capital or valid stop distance")
        capital_limit = balance * min(risk.max_exposure_pct, risk.max_position_pct) / 100
        raw_quantity = min(
            capital_limit / (trade.entry_price * (1 + fee)),
            balance * risk.risk_per_trade_pct / 100 / loss_per_unit,
        )
        step = Decimal(str(risk.quantity_step))
        quantity = float(
            (Decimal(str(raw_quantity)) / step).to_integral_value(rounding=ROUND_FLOOR) * step
        )
        checks = (
            (trade.entry_reference, bars[index][0]),
            (
                trade.stop,
                trade.entry_price - _atr_at_signal(bars, index, risk, offset - case.warmup),
            ),
            (trade.entry_price, trade.entry_reference * (1 + adverse)),
            (trade.exit_price, trade.exit_reference * (1 - adverse)),
            (trade.entry_fee, trade.entry_price * trade.quantity * fee),
            (trade.exit_fee, trade.exit_price * trade.quantity * fee),
            (
                trade.slippage_cost,
                trade.quantity * (trade.entry_reference + trade.exit_reference) * slip,
            ),
            (
                trade.spread_cost,
                trade.quantity * (trade.entry_reference + trade.exit_reference) * spread,
            ),
            (
                trade.net_pnl,
                trade.quantity * (trade.exit_price - trade.entry_price)
                - trade.entry_fee
                - trade.exit_fee,
            ),
            (trade.risk_budget, balance * risk.risk_per_trade_pct / 100),
            (trade.expected_stop_loss, trade.quantity * loss_per_unit),
        )
        if (
            not all(_equal(a, b) for a, b in checks)
            or not isclose(trade.quantity, quantity, rel_tol=0, abs_tol=1e-10)
            or trade.quantity < risk.min_quantity
            or trade.quantity * trade.entry_price < risk.min_notional
            or trade.quantity * trade.entry_price * (1 + fee) > capital_limit + 1e-8
        ):
            raise SemanticInconsistency("Trade PnL, sizing or costs contradict fills")
        gross = trade.quantity * (trade.exit_price - trade.entry_price)
        balance -= trade.entry_fee
        balance += gross - trade.exit_fee
    rejection_times = [r.time for r in data.rejections]
    if any(
        rejection.time.utcoffset() != timedelta(0)
        or not case.start < rejection.time < case.end
        or (rejection.time - case.start) % hour
        for rejection in data.rejections
    ) or rejection_times != sorted(set(rejection_times)):
        raise SemanticInconsistency("Invalid, duplicate or unordered rejection timestamp")
    equity, exposure = _reconcile_bars(data, case, risk, bars[offset : offset + case.bars])
    pnl = [t.net_pnl for t in data.trades]
    wins = [v for v in pnl if v > 0]
    losses = [v for v in pnl if v < 0]
    peak, drawdown = equity[0], 0.0
    for value in equity:
        peak = max(peak, value)
        drawdown = max(drawdown, (peak - value) / peak)
    expected = {
        "closed_trades": len(pnl),
        "return_pct": 100 * (equity[-1] / equity[0] - 1),
        "max_drawdown_pct": 100 * drawdown,
        "expectancy": sum(pnl) / len(pnl) if pnl else None,
        "profit_factor": sum(wins) / -sum(losses) if losses else None,
        "win_rate_pct": 100 * len(wins) / len(pnl) if pnl else None,
        "average_close_exposure_pct": 100 * sum(exposure[1:]) / case.bars,
        "fees_paid": sum(t.entry_fee + t.exit_fee for t in data.trades),
        "realized_net_pnl": sum(pnl),
        "slippage_cost_closed_trades": sum(t.slippage_cost for t in data.trades),
        "spread_cost_closed_trades": sum(t.spread_cost for t in data.trades),
        "rejected_entries": len(data.rejections),
    }
    if not _equal(equity[-1] - equity[0], sum(pnl)) or any(
        not _equal(getattr(data.metrics, key), val) for key, val in expected.items()
    ):
        raise SemanticInconsistency("Metrics, equity and operations do not reconcile")


def _atr_at_signal(bars, index, risk, first):
    start = index - risk.atr_period
    if start <= first:
        raise SemanticInconsistency("Insufficient true ranges at signal close")
    ranges = []
    for i in range(start, index):
        _, high, low, _, _ = bars[i]
        previous = bars[i - 1][3]
        ranges.append(max(high - low, abs(high - previous), abs(low - previous)))
    return sum(ranges) / risk.atr_period * risk.atr_multiplier


def _exit_for_bar(position, candle, when, last):
    opening, high, low, close, _ = candle
    if opening <= position.stop:
        return opening, "stop_gap", "open"
    if opening >= position.target:
        return position.target, "target_gap", "open"
    if (
        position.exit_bar_open == when
        and position.reason == "signal"
        and position.entry_time < when
    ):
        return opening, "signal", "open"
    if low <= position.stop:
        return position.stop, "stop", "intrabar"
    if high >= position.target:
        return position.target, "target", "intrabar"
    if last:
        return close, "end_of_study", "close"
    return None


def _reconcile_bars(data, case, risk, bars):
    balance = risk.initial_cash
    equity, exposure = [balance], [0.0]
    entries = {trade.entry_time: trade for trade in data.trades}
    rejected = {rejection.time for rejection in data.rejections}
    position = None
    hour = timedelta(hours=1)
    for index, candle in enumerate(bars):
        when = case.start + index * hour
        if when in rejected and (position is not None or when in entries):
            raise SemanticInconsistency("Rejected entry contradicts the position or a fill")
        if entry := entries.get(when):
            if position is not None:
                raise SemanticInconsistency("Entry while a position is open")
            position = entry
            balance -= entry.entry_fee
        if position is not None:
            fill = _exit_for_bar(position, candle, when, index == len(bars) - 1)
            if position.exit_bar_open == when:
                if (
                    fill is None
                    or not _equal(position.exit_reference, fill[0])
                    or (position.reason, position.exit_timing) != fill[1:]
                    or position.holding_bars
                    != (when - position.entry_time) // hour + (position.exit_timing != "open")
                ):
                    raise SemanticInconsistency(f"Exit inconsistent with authorized candle {when}")
                gross = position.quantity * (position.exit_price - position.entry_price)
                balance += gross - position.exit_fee
                position = None
            elif fill is not None:
                raise SemanticInconsistency(
                    f"Missing protective fill or final liquidation at {when}"
                )
        close = candle[3]
        value = balance
        fraction = 0.0
        if position is not None:
            value += position.quantity * (close - position.entry_price)
            if value > 0:
                fraction = position.quantity * close / value
        if not _equal(data.equity[index + 1], value) or not _equal(
            data.exposure[index + 1], fraction
        ):
            raise SemanticInconsistency(f"Equity or exposure cannot reconcile at {when + hour}")
        equity.append(value)
        exposure.append(fraction)
    if position is not None:
        raise SemanticInconsistency("Position remains open after mandatory liquidation")
    return equity, exposure
