"""Supertrend direction, reversal and independent numeric seed."""

import numpy as np
import pandas as pd

from quant_lab.new_mtf_features import indicators, supertrend


def test_supertrend_seed_and_reversals():
    close = np.r_[np.full(15, 100.0), np.full(10, 80.0), np.full(10, 130.0)]
    f = pd.DataFrame(
        dict(open=close, high=close + 1, low=close - 1, close=close, volume=1.0),
        index=pd.date_range("2020", periods=len(close), freq="h", tz="UTC"),
    )
    s = supertrend(f)
    assert s.st_line.iloc[:10].isna().all()
    assert s.st_line.iloc[10] == 94
    assert s.st_direction.iloc[10] == 1
    assert s.st_direction.iloc[15] == -1
    assert s.st_direction.iloc[25] == 1
    pd.testing.assert_frame_equal(supertrend(f.iloc[:23]), s.iloc[:23])
    values = indicators(f)
    assert not values.st_event.iloc[:20].any()
    assert values.st_touch_age.dropna().between(1, 3).all()


def test_pullback_requires_later_recovery():
    close = 100 + np.arange(60) * 0.3
    f = pd.DataFrame(
        dict(open=close - 0.1, high=close + 0.2, low=close - 0.2, close=close, volume=1.0),
        index=pd.date_range("2020", periods=60, freq="h", tz="UTC"),
    )
    f.iloc[58, f.columns.get_loc("low")] = indicators(f).ema20.iloc[58]
    values = indicators(f)
    assert values.st_event.iloc[59]
    assert values.st_touch_age.iloc[59] == 1
    assert not values.st_event.iloc[58]
    pd.testing.assert_frame_equal(indicators(f.iloc[:59]), values.iloc[:59])
