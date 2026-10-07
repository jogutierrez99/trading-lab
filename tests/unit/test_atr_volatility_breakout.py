import pandas as pd
import pytest
from test_trend_volatility_breakout_v1 import candles

from quant_lab.config import StrategyConfig
from quant_lab.strategies.registry import StrategyRegistry

NAME = "atr_volatility_breakout"


def strategy(**parameters):
    return (
        StrategyRegistry()
        .discover()
        .create(StrategyConfig(name=NAME, enabled=True, parameters=parameters))
    )


@pytest.mark.parametrize("short", [False, True])
def test_symmetric_entries_and_warmup(short):
    s, frame = strategy(), candles(short)
    signals = s.generate_signals(frame)
    expected = signals.short_entries if short else signals.long_entries
    opposite = signals.long_entries if short else signals.short_entries
    assert expected[-1] and not any(opposite)
    assert not any(expected[:999])
    assert not any(signals.long_exits) and not any(signals.short_exits)


def test_causal_prefix_future_mutation_and_gap_reset():
    s, frame = strategy(), candles(n=2200)
    full = s.prepare_features(frame)
    signals = s.generate_signals(frame)
    for end in (0, 1, 14, 199, 999, 1000, 1100, 1800):
        pd.testing.assert_frame_equal(
            s.prepare_features(frame.iloc[:end]), full.iloc[:end], check_freq=False
        )
        prefix = s.generate_signals(frame.iloc[:end])
        for name in ("long_entries", "short_entries", "long_exits", "short_exits"):
            assert getattr(prefix, name) == getattr(signals, name)[:end]
    changed = frame.copy()
    changed.iloc[1100:, :4] *= 2
    pd.testing.assert_frame_equal(s.prepare_features(changed).iloc[:1100], full.iloc[:1100])
    gap = frame.drop(frame.index[1100])
    features = s.prepare_features(gap)
    pd.testing.assert_frame_equal(
        features.iloc[1100:], s.prepare_features(gap.iloc[1100:]), check_freq=False
    )
    assert not features.ready.iloc[1100:2099].any()


@pytest.mark.parametrize("short", [False, True])
def test_previous_donchian_exit(short):
    s = strategy(exit_method="donchian")
    frame = candles(short)
    f = s.prepare_features(frame)
    assert f.exit_low.iloc[-1] == frame.low.iloc[-11:-1].min()
    assert f.exit_high.iloc[-1] == frame.high.iloc[-11:-1].max()
    last = f.iloc[[-1]].copy()
    last["close"] = last.exit_high + 1 if short else last.exit_low - 1
    method = s.generate_short_exits if short else s.generate_long_exits
    assert method(last) == [True]


@pytest.mark.parametrize(
    "params",
    [
        {"unknown": 1},
        {"atr_length": True},
        {"atr_stop_multiplier": 0.0},
        {"reward_risk": float("nan")},
        {"exit_method": "future"},
    ],
)
def test_strict_parameters(params):
    with pytest.raises(ValueError):
        strategy(**params)


@pytest.mark.parametrize("method", ["mean", "median"])
def test_prior_atr_reference_and_impulse(method):
    s = strategy(atr_reference_method=method)
    frame = candles()
    f = s.prepare_features(frame)
    history = f.atr.iloc[-51:-1]
    assert f.atr_reference.iloc[-1] == pytest.approx(
        history.mean() if method == "mean" else history.median()
    )
    assert f.impulse.iloc[-1] == pytest.approx(
        (frame.close.iloc[-1] - frame.close.iloc[-2]) / f.atr.iloc[-2]
    )
    changed = frame.copy()
    changed.iloc[-1, changed.columns.get_loc("high")] += 100
    newer = s.prepare_features(changed)
    assert newer.atr_reference.iloc[-1] == f.atr_reference.iloc[-1]
    assert newer.impulse.iloc[-1] == f.impulse.iloc[-1]
    assert newer.atr.iloc[-1] > f.atr.iloc[-1]


def test_expansion_and_impulse_are_independent_gates():
    s = strategy()
    f = s.prepare_features(candles()).iloc[[-1]].copy()
    assert s.generate_long_entries(f) == [True]
    f["atr_expansion"] = 1.0
    assert s.generate_long_entries(f) == [False]
    f["atr_expansion"] = 1.1
    f["impulse"] = s.parameters.impulse_atr_multiplier
    assert s.generate_long_entries(f) == [False]
