"""Keltner channel arithmetic and fresh-cross behavior."""

import numpy as np
import pandas as pd

from quant_lab.features import atr, ema
from quant_lab.new_mtf_features import indicators


def test_keltner_breakout_is_not_repeated_outside_channel():
    close = np.r_[np.full(50, 100.0), 115.0, 116.0, 117.0]
    f = pd.DataFrame(
        dict(open=close - 0.1, high=close + 1, low=close - 1, close=close, volume=1.0),
        index=pd.date_range("2020", periods=len(close), freq="h", tz="UTC"),
    )
    v = indicators(f)
    pd.testing.assert_series_equal(v.kc_upper, ema(f.close, 20) + 2 * atr(f, 20), check_names=False)
    pd.testing.assert_series_equal(v.kc_lower, ema(f.close, 20) - 2 * atr(f, 20), check_names=False)
    assert v.kc_event.iloc[50]
    assert not v.kc_event.iloc[51:].any()
    pd.testing.assert_frame_equal(indicators(f.iloc[:51]), v.iloc[:51])
