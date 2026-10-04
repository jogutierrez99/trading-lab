"""Range entries require failed excursions, quality and sideways regime."""

import pandas as pd
import pytest
from test_intraday_contracts import candles, strategy


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize("gate", ["regime", "quality", "excursion", "reclaim", "zone"])
def test_range_requires_rejection_and_regime(side, gate):
    s = strategy("range_mean_reversion_v1")
    f = pd.DataFrame(
        {
            "range_regime": [True],
            "range_width_atr": [4.0],
            "range_low": [90.0],
            "range_high": [110.0],
            "low": [89.0 if side == 1 else 108.0],
            "high": [92.0 if side == 1 else 111.0],
            "close": [91.0 if side == 1 else 109.0],
            "range_position": [0.05 if side == 1 else 0.95],
        }
    )
    method = s.generate_long_entries if side == 1 else s.generate_short_entries
    opposite = s.generate_short_entries if side == 1 else s.generate_long_entries
    assert method(f) == [True] and opposite(f) == [False]
    if gate == "regime":
        f["range_regime"] = False
    elif gate == "quality":
        f["range_width_atr"] = 2.9
    elif gate == "excursion":
        f["low" if side == 1 else "high"] = 90.0 if side == 1 else 110.0
    elif gate == "reclaim":
        f["close"] = 90.0 if side == 1 else 110.0
    else:
        f["range_position"] = 0.2 if side == 1 else 0.8
    assert method(f) == [False]


def test_range_levels_are_prior_frozen_midpoint_and_atr_buffer():
    s, frame = strategy("range_mean_reversion_v1"), candles()
    f = s.prepare_features(frame)
    assert f.range_high.iloc[-1] == frame.high.iloc[-33:-1].max()
    assert f.range_low.iloc[-1] == frame.low.iloc[-33:-1].min()
    assert f.range_mid.iloc[-1] == (f.range_high.iloc[-1] + f.range_low.iloc[-1]) / 2
    levels = s.entry_levels(frame)
    pd.testing.assert_series_equal(levels.long_target, f.range_mid, check_names=False)
    assert (levels.long_stop.dropna() < f.range_low.loc[levels.long_stop.dropna().index]).all()
    assert (levels.short_stop.dropna() > f.range_high.loc[levels.short_stop.dropna().index]).all()
    changed = frame.copy()
    changed.iloc[-1, :4] *= 2
    newer = s.prepare_features(changed)
    for column in ("range_high", "range_low", "range_mid"):
        assert newer[column].iloc[-1] == f[column].iloc[-1]


@pytest.mark.parametrize(
    "column,value", [("hour_adx", 20.0), ("hour_slope_pct", 0.1), ("hour_slope_pct", -0.1)]
)
def test_sideways_filter_is_strict(column, value):
    s = strategy("range_mean_reversion_v1")
    # Recompute actual regime using causal features rather than overriding its flag.
    frame = candles()
    # The regime formula is tested by replacing the context calculator.
    from unittest.mock import patch

    import quant_lab.strategies.range_mean_reversion_v1 as module

    original = module.context

    def context(*args):
        result = original(*args)
        result["hour_adx"] = 10.0
        result["hour_slope_pct"] = 0.0
        result[column] = value
        return result

    with patch.object(module, "context", context):
        assert not s.prepare_features(frame).range_regime.any()


def test_zero_width_and_asymmetric_zones_rejected():
    s = strategy("range_mean_reversion_v1")
    frame = candles()
    frame.iloc[:, :4] = 100.0
    f = s.prepare_features(frame)
    assert f.range_position.isna().all()
    assert not any(s.generate_long_entries(f)) and not any(s.generate_short_entries(f))
    with pytest.raises(ValueError):
        strategy(s.name, lower_zone=0.1, upper_zone=0.8)
