"""Explicit signal gates, exact windows, warmup, gaps and causal invariance."""

import numpy as np
import pandas as pd
import pytest

from quant_lab.config import MarketConfig, StrategyConfig
from quant_lab.features import true_range
from quant_lab.strategies.registry import StrategyRegistry
from quant_lab.strategies.trend_volatility_breakout_v1 import Parameters


def strategy(**parameters):
    return (
        StrategyRegistry()
        .discover()
        .create(
            StrategyConfig(
                name="trend_volatility_breakout_v1",
                version="1.0.1",
                enabled=True,
                market=MarketConfig(timeframe="1h"),
                parameters=parameters,
            )
        )
    )


def candles(short=False, n=1200):
    price = 100 + np.arange(n) * 0.3
    price[-1] += 5
    if short:
        price = 500 - price
    return pd.DataFrame(
        {"open": price, "high": price + 0.1, "low": price - 0.1, "close": price, "volume": 10.0},
        index=pd.date_range("2022-01-01", periods=n, freq="h", tz="UTC"),
    )


@pytest.mark.parametrize("short", [False, True])
def test_valid_long_short_close_signals(short):
    s, frame = strategy(), candles(short)
    f = s.prepare_features(frame)
    signals = s.generate_signals(frame)
    expected = signals.short_entries if short else signals.long_entries
    opposite = signals.long_entries if short else signals.short_entries
    assert expected[-1] and not any(opposite)
    assert not any(expected[:999])
    assert not any(signals.long_exits) and not any(signals.short_exits)
    assert (f.available_at == frame.index + pd.Timedelta(hours=1)).all()


@pytest.mark.parametrize("short", [False, True])
@pytest.mark.parametrize("gate", ["ready", "trend", "slope", "breakout", "expansion"])
def test_each_required_gate_and_strict_boundaries(short, gate):
    s, frame = strategy(atr_expansion_threshold=1.25), candles(short)
    f = s.prepare_features(frame).iloc[[-1]].copy()
    method = s.generate_short_entries if short else s.generate_long_entries
    assert method(f) == [True]
    if gate == "ready":
        f["ready"] = False
    elif gate == "trend":
        f["trend_ema"] = f.close
    elif gate == "slope":
        f["trend_slope"] = 1.0 if short else -1.0
    elif gate == "breakout":
        f["breakout_low" if short else "breakout_high"] = f.close
    else:
        f["atr_expansion"] = 1.249
    assert method(f) == [False]


def test_expansion_threshold_inclusive():
    s = strategy(atr_expansion_threshold=1.25)
    f = s.prepare_features(candles()).iloc[[-1]].copy()
    f["atr_expansion"] = 1.25
    assert s.generate_long_entries(f) == [True]


def test_exact_ema_slope_breakout_atr_reference_windows():
    s, frame = strategy(), candles()
    f = s.prepare_features(frame)
    expected_ema = frame.close.ewm(span=200, adjust=False, min_periods=200).mean()
    pd.testing.assert_series_equal(f.trend_ema, expected_ema, check_names=False)
    assert f.trend_slope.iloc[-1] == pytest.approx(expected_ema.iloc[-1] - expected_ema.iloc[-6])
    assert f.breakout_high.iloc[-1] == frame.high.iloc[-21:-1].max()
    assert f.breakout_low.iloc[-1] == frame.low.iloc[-21:-1].min()
    tr = true_range(frame)
    assert f.atr.iloc[-1] == pytest.approx(tr.iloc[-14:].mean())
    history = [tr.iloc[t - 13 : t + 1].mean() for t in range(len(frame) - 51, len(frame) - 1)]
    assert f.atr_reference.iloc[-1] == pytest.approx(np.mean(history))
    assert f.atr_expansion.iloc[-1] == pytest.approx(f.atr.iloc[-1] / np.mean(history))
    changed = frame.copy()
    changed.iloc[-1, changed.columns.get_loc("high")] += 100
    changed.iloc[-1, changed.columns.get_loc("low")] -= 50
    newer = s.prepare_features(changed)
    assert newer.breakout_high.iloc[-1] == f.breakout_high.iloc[-1]
    assert newer.breakout_low.iloc[-1] == f.breakout_low.iloc[-1]
    assert newer.atr_reference.iloc[-1] == f.atr_reference.iloc[-1]
    assert newer.atr.iloc[-1] > f.atr.iloc[-1]


@pytest.mark.parametrize(
    "parameters,expected",
    [
        ({}, 1000),
        ({"trend_length": 100}, 500),
        ({"trend_length": 10, "slope_lookback": 2, "atr_length": 20}, 71),
        ({"trend_length": 10, "breakout_length": 100}, 101),
        ({"trend_length": 10, "atr_length": 100}, 151),
    ],
)
def test_exact_warmup(parameters, expected):
    s, frame = strategy(**parameters), candles()
    assert s.required_warmup(s.parameters.model_dump(), "1h") == expected
    f = s.prepare_features(frame)
    assert not f.ready.iloc[: expected - 1].any()
    assert f.ready.iloc[expected - 1]


def test_full_prefix_and_future_mutation_invariance():
    s, frame = strategy(), candles()
    full, signals = s.prepare_features(frame), s.generate_signals(frame)
    for end in (0, 1, 14, 64, 65, 199, 499, 500, 999, 1000, 1100, 1199):
        part = s.prepare_features(frame.iloc[:end])
        pd.testing.assert_frame_equal(part, full.iloc[:end], check_freq=False)
        prefix = s.generate_signals(frame.iloc[:end])
        for name in ("long_entries", "short_entries", "long_exits", "short_exits"):
            assert getattr(prefix, name) == getattr(signals, name)[:end]
    changed = frame.copy()
    changed.iloc[1100:, :4] *= 2
    pd.testing.assert_frame_equal(s.prepare_features(changed).iloc[:1100], full.iloc[:1100])


def test_gap_restarts_all_indicators_and_warmup():
    s = strategy(trend_length=10, slope_lookback=2, atr_length=14)
    frame = candles(n=400).drop(candles(n=400).index[220])
    f = s.prepare_features(frame)
    tail = frame.iloc[220:]
    pd.testing.assert_frame_equal(f.iloc[220:], s.prepare_features(tail), check_freq=False)
    assert not f.ready.iloc[220:284].any()
    assert f.ready.iloc[284]


@pytest.mark.parametrize("kind", ["reverse", "duplicate", "timezone", "alignment"])
def test_timestamp_guards(kind):
    frame = candles()
    if kind == "reverse":
        frame = frame.iloc[::-1]
    elif kind == "duplicate":
        frame = pd.concat([frame.iloc[:1], frame])
    elif kind == "timezone":
        frame.index = frame.index.tz_convert("Europe/Madrid")
    else:
        frame.index += pd.Timedelta(minutes=1)
    with pytest.raises(ValueError):
        strategy().prepare_features(frame)


def test_zero_atr_no_expansion_or_signal():
    frame = candles()
    frame[["open", "high", "low", "close"]] = 100.0
    s = strategy()
    f = s.prepare_features(frame)
    assert f.atr_expansion.isna().all() and not f.ready.any()
    assert not any(s.generate_signals(frame).long_entries)


@pytest.mark.parametrize(
    "parameters",
    [
        {"trend_length": 1},
        {"trend_length": "200"},
        {"slope_lookback": 0},
        {"atr_length": True},
        {"breakout_length": 1},
        {"atr_reference_length": 49},
        {"atr_expansion_threshold": float("nan")},
        {"atr_stop_multiplier": float("inf")},
        {"reward_risk": 0.0},
        {"unknown": 1},
    ],
)
def test_invalid_parameters(parameters):
    with pytest.raises(ValueError):
        strategy(**parameters)


def test_registry_serialization_and_timeframe_guard():
    s = strategy()
    assert Parameters.model_validate_json(s.parameters.model_dump_json()) == s.parameters
    assert StrategyConfig.model_validate_json(s.config.model_dump_json()) == s.config
    assert s.metadata()["version"] == "1.0.1"
    row = next(r for r in StrategyRegistry().discover().catalogue() if r["strategy_id"] == s.name)
    assert row["timeframes"] == ("1h",) and row["execution"] == "ohlcv"
    assert row["modes"] == ("LONG_ONLY", "SHORT_ONLY", "LONG_SHORT")
    with pytest.raises(ValueError, match="1h"):
        s.required_warmup({}, "15m")
