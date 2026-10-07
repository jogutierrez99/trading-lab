import pandas as pd
import pytest
from test_trend_volatility_breakout_v1 import candles

from quant_lab.config import StrategyConfig
from quant_lab.strategies.registry import StrategyRegistry

NAME = "donchian_trend_breakout"


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


def test_entry_channel_excludes_signal_bar_and_matches_hybrid_structure():
    from quant_lab.strategies.donchian_atr_breakout import DonchianAtrBreakoutStrategy

    s = strategy(breakout_length=40)
    frame = candles()
    f = s.prepare_features(frame)
    assert f.breakout_high.iloc[-1] == frame.high.iloc[-41:-1].max()
    changed = frame.copy()
    changed.iloc[-1, changed.columns.get_loc("high")] += 100
    assert s.prepare_features(changed).breakout_high.iloc[-1] == f.breakout_high.iloc[-1]
    h = DonchianAtrBreakoutStrategy(
        StrategyConfig(
            name="donchian_atr_breakout", enabled=True, parameters={"breakout_length": 40}
        )
    )
    hf = h.prepare_features(frame)
    for col in ("trend_ema", "trend_slope", "breakout_high", "breakout_low", "atr"):
        pd.testing.assert_series_equal(f[col], hf[col])
    assert all(
        not hybrid or pure
        for hybrid, pure in zip(
            h.generate_signals(frame).long_entries,
            s.generate_signals(frame).long_entries,
            strict=True,
        )
    )


@pytest.mark.parametrize("trend_filter", ["ema_slope", "price_ema", "dual_ema", "off"])
def test_trend_filter_is_explicit_and_causal(trend_filter):
    s = strategy(trend_filter=trend_filter)
    frame = candles()
    assert s.generate_signals(frame).long_entries[-1]
    assert (
        s.generate_signals(frame.iloc[:1100]).long_entries
        == s.generate_signals(frame).long_entries[:1100]
    )
