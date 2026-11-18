"""Independent causal decision replay plus 5.5A's accounting reconciliation."""

from decimal import ROUND_FLOOR, Decimal
from math import fsum, isfinite

from .historical_pilot_contract import window
from .isolated_study_contract import SemanticInconsistency, _check_case


def crossings(closes):
    previous = None
    for i in range(len(closes)):
        if i < 199:
            yield False, False
            continue
        fast = fsum(closes[i - 49 : i + 1]) / 50
        slow = fsum(closes[i - 199 : i + 1]) / 200
        delta = fast - slow
        yield (
            previous is not None and previous <= 0 < delta,
            previous is not None and previous >= 0 > delta,
        )
        previous = delta


def protective(candle, stop, target, *, signal, last):
    opening, high, low, close, _ = candle
    if opening <= stop:
        return opening, "stop_gap", "open"
    if opening >= target:
        return target, "target_gap", "open"
    if signal:
        return opening, "signal", "open"
    if low <= stop:
        return stop, "stop", "intrabar"
    if high >= target:
        return target, "target", "intrabar"
    if last:
        return close, "end_of_study", "close"
    return None


def quote(bars, i, risk, balance, fee, adverse):
    ranges = []
    for j in range(i - 14, i):
        _, high, low, _, _ = bars[j]
        previous_close = bars[j - 1][3]
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    distance = fsum(ranges) / 14 * 2
    if distance <= 0 or not isfinite(distance):
        return "invalid_stop_distance"
    if balance <= 0:
        return "insufficient_equity"
    price = bars[i][0] * (1 + adverse)
    stop, target = price - distance, price + 2 * distance
    if stop <= 0 or not all(isfinite(v) for v in (price, stop, target)):
        return "invalid_protective_levels"
    estimated = stop * (1 - adverse)
    loss = price - estimated + fee * (price + estimated)
    ceiling = balance * min(risk.max_position_pct, risk.max_exposure_pct) / 100
    raw = min(ceiling / (price * (1 + fee)), balance * risk.risk_per_trade_pct / 100 / loss)
    step = Decimal(str(risk.quantity_step))
    units = float((Decimal(str(raw)) / step).to_integral_value(rounding=ROUND_FLOOR) * step)
    if units < risk.min_quantity:
        return "below_min_quantity"
    if units * price < risk.min_notional:
        return "below_min_notional"
    return price, stop, target, units


def audit_case(frame, case, risk, result):
    candles = window(frame, case)
    bars = candles.to_numpy().tolist()
    stamps = candles.index.to_pydatetime()
    signals = list(crossings([bar[3] for bar in bars]))
    entries = {item.entry_time: item for item in result.trades}
    rejections = {item.time: item.reason for item in result.rejections}
    if len(entries) != len(result.trades) or len(rejections) != len(result.rejections):
        raise SemanticInconsistency("Duplicate fills or rejections")
    balance = risk.initial_cash
    position = None
    declared = None
    fee = case.costs.trading_fee_pct / 100
    adverse = (case.costs.slippage_pct + case.costs.spread_pct / 2) / 100
    for i in range(case.warmup, len(bars)):
        when = stamps[i]
        buy, sell = signals[i - 1] if i > case.warmup else (False, False)
        trade = entries.pop(when, None)
        reason = rejections.pop(when, None)
        opened = False
        if position is None and buy:
            estimate = quote(bars, i, risk, balance, fee, adverse)
            if isinstance(estimate, str):
                if trade is not None or reason != estimate:
                    raise SemanticInconsistency(f"Missing or incorrect rejection at {when}")
            else:
                if trade is None or reason is not None:
                    raise SemanticInconsistency(f"Missing required NEXT_OPEN fill at {when}")
                position, declared = estimate, trade
                balance -= estimate[0] * estimate[3] * fee
                opened = True
        elif trade is not None or reason is not None:
            raise SemanticInconsistency(f"Entry without an executable causal crossover at {when}")
        if position is None:
            continue
        price, stop, target, units = position
        fill = protective(
            bars[i], stop, target, signal=sell and not opened, last=i == len(bars) - 1
        )
        if fill is None:
            if declared.exit_bar_open == when:
                raise SemanticInconsistency(f"Exit without causal signal or protection at {when}")
            continue
        reference, expected_reason, timing = fill
        if declared.exit_bar_open != when or (declared.reason, declared.exit_timing) != (
            expected_reason,
            timing,
        ):
            raise SemanticInconsistency(f"Missing or incorrect exit decision at {when}")
        sale = reference * (1 - adverse)
        balance += units * (sale - price) - units * sale * fee
        position = declared = None
    if entries or rejections or position is not None:
        raise SemanticInconsistency(
            "Unexpected events outside audited period or missing liquidation"
        )
    _check_case(result, case, risk, {"start": stamps[0].isoformat(), "ohlcv": bars})
