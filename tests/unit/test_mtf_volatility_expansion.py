"""Causal compression median, recent window and expansion breakout."""

import numpy as np
import pandas as pd

from quant_lab.new_mtf_features import indicators


def test_compression_then_expansion():
    t = np.arange(200)
    close = 100 + np.sin(t) * np.where(t < 150, 5.0, 0.1)
    close[-1] = 115
    f = pd.DataFrame(
        dict(open=close - 0.1, high=close + 0.5, low=close - 0.5, close=close, volume=1.0),
        index=pd.date_range("2020", periods=len(close), freq="h", tz="UTC"),
    )
    v = indicators(f)
    assert v.width_median.iloc[:118].isna().all()
    assert v.width_median.iloc[-1] == v.bandwidth.iloc[-100:].median()
    assert v.compression.iloc[-2]
    assert v.expansion_event.iloc[-1]
    assert v.channel_high.iloc[-1] == f.high.iloc[-21:-1].max()
    pd.testing.assert_frame_equal(indicators(f.iloc[:180]), v.iloc[:180])
