import numpy as np
import pandas as pd
import pytest

from quant_lab.config import StrategyConfig
from quant_lab.indicators import adx, volatility_fractions
from quant_lab.strategies.registry import StrategyRegistry


def test_adx_hand_values_and_constant_series():
    frame = pd.DataFrame(
        {
            "high": [11.0, 12.0, 14.0, 13.0, 15.0],
            "low": [9.0, 10.0, 12.0, 11.0, 13.0],
            "close": [10.0, 11.0, 13.0, 12.0, 14.0],
        }
    )
    value = adx(frame, 2)
    assert value.iloc[:3].isna().all()
    assert value.iloc[3] == pytest.approx(60)
    assert value.iloc[4] == pytest.approx(64.615384615)
    flat = pd.DataFrame({"high": [10.0] * 40, "low": [10.0] * 40, "close": [10.0] * 40})
    assert adx(flat).iloc[:27].isna().all()
    assert adx(flat).iloc[27:].eq(0).all()


@pytest.mark.parametrize("name", ["vol_momentum", "donchian_adx", "bb_squeeze", "regime_meanrev"])
def test_new_strategies_prefix_invariance_and_warmup(name):
    rng = np.random.default_rng(7)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 1050))))
    frame = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 10.0}
    )
    before = frame.copy(deep=True)
    strategy = StrategyRegistry().discover().create(StrategyConfig(name=name, enabled=True))
    features, signals = strategy.prepare_features(frame), strategy.generate_signals(frame)
    for length in (1, 14, 27, 28, 200, 336, 720, 721, 739, 740, 763, 764, 768, 1020):
        pd.testing.assert_frame_equal(
            strategy.prepare_features(frame.iloc[:length]), features.iloc[:length]
        )
        partial = strategy.generate_signals(frame.iloc[:length])
        assert partial.long_entries == signals.long_entries[:length]
        assert partial.long_exits == signals.long_exits[:length]
    pd.testing.assert_frame_equal(frame, before)
    if name == "vol_momentum":
        assert features.momentum.iloc[336] == pytest.approx(close.iloc[336] / close.iloc[0] - 1)
        assert not any(signals.long_entries[:720])
    if name == "bb_squeeze":
        assert features.threshold.iloc[739] == pytest.approx(
            features.bandwidth.iloc[19:739].quantile(0.2)
        )
        assert features.recent_squeeze.iloc[:763].isna().all()
        assert features.recent_squeeze.iloc[800] == features["squeeze"].iloc[776:800].max()
    if name == "donchian_adx":
        assert features.upper.iloc[20] == frame.high.iloc[:20].max()
    with pytest.raises(ValueError):
        StrategyRegistry().discover().create(
            StrategyConfig(name=name, enabled=True, parameters={"typo": 1})
        )


def test_volatility_fraction_sample_std_annualization_caps_and_zero():
    close = pd.Series([100.0, 101.0, 99.0, 104.0, 102.0])
    vol = close.pct_change(fill_method=None).iloc[-3:].std(ddof=1) * np.sqrt(8760)
    expected = np.clip(0.2 / vol, 0.05, 0.25)
    fractions = volatility_fractions(close, 3, 20.0, 5.0, 25.0)
    assert fractions.iloc[-1] == pytest.approx(expected)
    assert fractions.iloc[:3].isna().all()
    assert volatility_fractions(pd.Series([100.0] * 10), 3, 20.0, 5.0, 25.0).isna().all()
