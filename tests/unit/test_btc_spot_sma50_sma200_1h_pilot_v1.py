"""Synthetic signal checks on native hourly UTC candles."""

import pandas as pd
import pytest
from pydantic import ValidationError

from quant_lab.config import StrategyConfig
from quant_lab.strategies.btc_spot_sma50_sma200_1h_pilot_v1 import (
    BtcSpotSma50Sma2001hPilotV1Strategy,
    Parameters,
)
from quant_lab.strategies.registry import StrategyRegistry


@pytest.fixture
def strategy():
    return BtcSpotSma50Sma2001hPilotV1Strategy(
        StrategyConfig(name=BtcSpotSma50Sma2001hPilotV1Strategy.name)
    )


def hourly_candles(closes: list[float]) -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=len(closes), freq="1h", tz="UTC")
    close = pd.Series(closes, index=index, dtype=float)
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0}
    )


@pytest.fixture
def crossover_candles():
    return hourly_candles([100.0] * 240 + [110.0, 110.0, 70.0, 110.0, 100.0, 110.0])


def test_registry_capabilities(strategy):
    cls = StrategyRegistry().discover().implementation(strategy.name)
    assert cls is type(strategy)
    assert cls.lab_timeframes == ("1h",)
    assert cls.lab_modes == ("LONG_ONLY",)
    assert cls.lab_execution == "ohlcv"
    assert cls.required_warmup({}, "1h") == 240


@pytest.mark.parametrize(
    "parameters",
    [{"fast_sma_period": 49}, {"slow_sma_period": 201}, {"unknown_period": 14}],
)
def test_rejects_parameters_outside_frozen_configuration(parameters):
    with pytest.raises(ValidationError):
        Parameters.model_validate(parameters)


def test_crossovers_at_close(strategy, crossover_candles):
    candles = crossover_candles
    original = candles.copy(deep=True)
    features = strategy.prepare_features(candles)
    signals = strategy.generate_signals(candles)

    pd.testing.assert_frame_equal(candles, original)
    pd.testing.assert_index_equal(features.index, candles.index)
    assert features["fast_sma"].iloc[240] == pytest.approx(100.2)
    assert features["slow_sma"].iloc[240] == pytest.approx(100.05)
    assert features["fast_sma"].iloc[243] == features["slow_sma"].iloc[243] == 100.0
    assert [i for i, signal in enumerate(signals.long_entries) if signal] == [240, 245]
    assert [i for i, signal in enumerate(signals.long_exits) if signal] == [242]
    assert signals.short_entries == signals.short_exits == (False,) * len(candles)


def test_requires_complete_current_and_previous_averages(strategy):
    candles = hourly_candles([100.0] * 199 + [110.0, 100.0])
    features = strategy.prepare_features(candles)
    signals = strategy.generate_signals(candles)
    assert features["fast_sma"].iloc[:49].isna().all()
    assert features["fast_sma"].iloc[49] == 100.0
    assert features["slow_sma"].iloc[:199].isna().all()
    assert features["fast_sma"].iloc[199] > features["slow_sma"].iloc[199]
    assert not any(signals.long_entries)
    assert not any(signals.long_exits)

    missing_close = hourly_candles([100.0] * 200 + [float("nan")] + [110.0] * 200)
    signals = strategy.generate_signals(missing_close)
    assert not any(signals.long_entries)
    assert not any(signals.long_exits)


@pytest.mark.parametrize("end", [0, 49, 199, 200, 240, 241, 242, 243, 244, 245])
def test_future_candles_do_not_change_features_or_signals(strategy, crossover_candles, end):
    prefix = crossover_candles.iloc[:end]
    pd.testing.assert_frame_equal(
        strategy.prepare_features(prefix),
        strategy.prepare_features(crossover_candles).iloc[:end],
    )
    full = strategy.generate_signals(crossover_candles)
    partial = strategy.generate_signals(prefix)
    assert partial.long_entries == full.long_entries[:end]
    assert partial.long_exits == full.long_exits[:end]
    assert partial.short_entries == full.short_entries[:end]
    assert partial.short_exits == full.short_exits[:end]
