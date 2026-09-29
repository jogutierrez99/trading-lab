import pytest
from pydantic import ValidationError

from quant_lab.config import StrategyConfig
from quant_lab.strategies.base import BaseStrategy
from quant_lab.strategies.registry import StrategyRegistry


def test_registry_and_signals(example_class):
    registry = StrategyRegistry()
    registry.register(example_class)
    assert registry.names() == ("example",)
    strategy = registry.create(StrategyConfig(name="example", enabled=True))
    signals = strategy.generate_signals([9.0, 10.0, 11.0])
    assert signals.long_entries == (False, False, True)
    assert signals.long_exits == (True, True, False)
    assert signals.short_entries == (True, False, False)
    assert signals.short_exits == (False, True, True)
    assert strategy.metadata()["parameters"] == {"threshold": 10.0}
    assert strategy.generate_signals([]).long_entries == ()


def test_registry_errors_and_isolation(example_class):
    registry = StrategyRegistry()
    registry.register(example_class)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(example_class)
    with pytest.raises(TypeError, match="abstract"):
        registry.register(BaseStrategy)
    with pytest.raises(ValueError, match="disabled"):
        registry.create(StrategyConfig(name="example"))
    with pytest.raises(ValueError, match="Unknown"):
        StrategyRegistry().create(StrategyConfig(name="example", enabled=True))
    with pytest.raises(ValueError, match="version"):
        registry.create(StrategyConfig(name="example", version="2.0.0", enabled=True))
    with pytest.raises(ValidationError):
        registry.create(StrategyConfig(name="example", enabled=True, parameters={"typo": 1}))


def test_implemented_discovery_is_idempotent():
    registry = StrategyRegistry().discover()
    expected = (
        "atr_breakout",
        "bb_squeeze",
        "bollinger_regime_reversal",
        "channel_break_retest",
        "donchian_adx",
        "dual_momentum",
        "ema_pullback",
        "low_vol_pullback",
        "mean_reversion",
        "mtf_bollinger",
        "mtf_donchian",
        "mtf_ema_adx",
        "mtf_keltner_breakout",
        "mtf_momentum",
        "mtf_roc_momentum",
        "mtf_supertrend_pullback",
        "mtf_trend_pullback",
        "mtf_volatility_expansion",
        "regime_meanrev",
        "regime_trend",
        "rsi_momentum_reset",
        "time_series_momentum",
        "trend_acceleration",
        "trend_following",
        "trend_rsi_pullback_v1",
        "trend_strength",
        "vol_contraction_expansion",
        "vol_expansion_trend",
        "vol_momentum",
    )
    assert registry.names() == expected
    assert registry.discover().names() == expected


@pytest.mark.parametrize("values", [[True], [1, 0], [None, False]])
def test_invalid_signal_shape_or_type(example_class, values):
    strategy = example_class(StrategyConfig(name="example"))
    strategy.generate_long_entries = lambda features: values
    with pytest.raises(ValueError, match="one Python bool"):
        strategy.generate_signals([9, 11])
