import pandas as pd
import pytest
from test_trend_volatility_breakout_v1 import candles

from quant_lab.config import StrategyConfig
from quant_lab.strategies.registry import StrategyRegistry

NAME = "donchian_atr_breakout"


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


def test_frozen_entry_reuse_exact_equivalence():
    from test_trend_volatility_breakout_v1 import strategy as frozen

    for short in (False, True):
        frame = candles(short)
        original = frozen(breakout_length=40, atr_expansion_threshold=1.25)
        reused = strategy(breakout_length=40, atr_expansion_threshold=1.25)
        assert original.generate_signals(frame) == reused.generate_signals(frame)
        f = original.prepare_features(frame)
        pd.testing.assert_frame_equal(f, reused.prepare_features(frame)[f.columns])
