import numpy as np
import pandas as pd
import pytest

from quant_lab.features import atr, baseline_features, sma, true_range


def test_indicator_values_and_warmup():
    frame = pd.DataFrame(
        {
            "high": [11.0, 15.0, 14.0, 20.0],
            "low": [9.0, 12.0, 8.0, 17.0],
            "close": [10.0, 14.0, 9.0, 19.0],
        }
    )
    np.testing.assert_allclose(true_range(frame), [np.nan, 5.0, 6.0, 11.0], equal_nan=True)
    np.testing.assert_allclose(atr(frame, 2), [np.nan, np.nan, 5.5, 8.5], equal_nan=True)
    np.testing.assert_allclose(sma(frame.close, 2), [np.nan, 12.0, 11.5, 14.0], equal_nan=True)


def test_baseline_prefix_invariance_and_input_preserved():
    rng = np.random.default_rng(42)
    close = pd.Series(
        100 + rng.uniform(0, 20, 260),
        index=pd.date_range("2024-01-01", periods=260, freq="h", tz="UTC"),
    )
    frame = pd.DataFrame(
        {"open": close, "high": close + 2, "low": close - 2, "close": close, "volume": 1.0}
    )
    original = frame.copy(deep=True)
    full = baseline_features(frame)
    for length in [1, 14, 15, 49, 50, 199, 200, 201, 250]:
        pd.testing.assert_frame_equal(baseline_features(frame.iloc[:length]), full.iloc[:length])
    assert full.sma_200.iloc[:199].isna().all()
    assert full.atr_14.iloc[:14].isna().all()
    assert full.iloc[200:].notna().all().all()
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("period", [0, -1, True, 2.5])
def test_invalid_period(period):
    with pytest.raises(ValueError):
        sma(pd.Series([1.0]), period)
