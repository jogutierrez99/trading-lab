import numpy as np
import pandas as pd
import pytest

from quant_lab.config import StrategyConfig
from quant_lab.features import ema, rsi
from quant_lab.strategies.registry import StrategyRegistry


def make_strategy(name, **parameters):
    return (
        StrategyRegistry()
        .discover()
        .create(StrategyConfig(name=name, enabled=True, parameters=parameters))
    )


def test_ema_and_wilder_rsi_hand_values():
    close = pd.Series([10.0, 12.0, 11.0, 14.0, 13.0])
    assert ema(close, 3).iloc[2] == 11.0
    values = rsi(close, 3)
    assert values.iloc[:3].isna().all()
    assert values.iloc[3] == pytest.approx(100 * 5 / 6)
    assert values.iloc[4] == pytest.approx(100 * 10 / 15)
    assert rsi(pd.Series([5.0] * 20), 3).iloc[3:].eq(50).all()
    assert rsi(pd.Series(range(20), dtype=float), 3).iloc[3:].eq(100).all()
    assert rsi(pd.Series(range(20, 0, -1), dtype=float), 3).iloc[3:].eq(0).all()


@pytest.mark.parametrize("name", ["trend_following", "mean_reversion", "time_series_momentum"])
def test_all_features_signals_prefix_invariant_and_input_unchanged(name):
    rng = np.random.default_rng(41)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 850))))
    frame = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 10.0}
    )
    original = frame.copy(deep=True)
    strategy = make_strategy(name)
    features = strategy.prepare_features(frame)
    full = strategy.generate_signals(frame)
    for size in [1, 14, 15, 20, 199, 200, 337, 400, 721, 849]:
        pd.testing.assert_frame_equal(
            strategy.prepare_features(frame.iloc[:size]), features.iloc[:size]
        )
        partial = strategy.generate_signals(frame.iloc[:size])
        for field in ("long_entries", "long_exits", "short_entries", "short_exits"):
            assert getattr(partial, field) == getattr(full, field)[:size]
    pd.testing.assert_frame_equal(frame, original)
    with pytest.raises(ValueError):
        make_strategy(name, unexpected=True)


def test_donchian_excludes_current_bar_and_long_short_behavior():
    strategy = make_strategy("trend_following", donchian_period=2, ema_period=2)
    frame = pd.DataFrame(
        {
            "close": [10.0, 10.0, 12.0, 7.0],
            "high": [11.0, 11.0, 13.0, 12.0],
            "low": [9.0, 9.0, 9.0, 6.0],
        }
    )
    features = strategy.prepare_features(frame)
    assert features.upper.iloc[2] == 11
    signals = strategy.generate_signals(frame)
    assert signals.long_entries == (False, False, True, False)
    assert signals.short_entries == (False, False, False, True)
    assert not any(signals.long_exits)


def test_bollinger_population_std_and_meanrev_rules():
    strategy = make_strategy("mean_reversion", bollinger_period=3, rsi_period=2, bollinger_std=1.0)
    frame = pd.DataFrame({"close": [10.0, 10.0, 4.0, 15.0, 10.0]})
    features = strategy.prepare_features(frame)
    assert features.middle.iloc[2] == 8
    assert features.lower.iloc[2] == pytest.approx(8 - np.sqrt(8))
    signals = strategy.generate_signals(frame)
    assert signals.long_entries[2]
    assert signals.short_entries[3]
    assert signals.long_exits[3]
    assert signals.short_exits[2]
