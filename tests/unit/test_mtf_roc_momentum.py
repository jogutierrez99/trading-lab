"""ROC percentages, acceleration and previous-only breakout."""

import numpy as np
import pandas as pd

from quant_lab.new_mtf_features import indicators


def test_roc_acceleration_and_shifted_high():
    close = np.r_[np.linspace(120, 100, 60), 101, 102, 103, 105, 110]
    f = pd.DataFrame(
        dict(open=close - 0.1, high=close + 0.5, low=close - 0.5, close=close, volume=1.0),
        index=pd.date_range("2020", periods=len(close), freq="h", tz="UTC"),
    )
    v = indicators(f)
    assert v.roc5.iloc[-1] == 100 * (110 / close[-6] - 1)
    assert v.roc20.iloc[-1] == 100 * (110 / close[-21] - 1)
    assert v.channel_high.iloc[-1] == f.high.iloc[-21:-1].max()
    assert v.roc_accelerating.iloc[-1] and v.roc_event.iloc[-1]
    changed = f.copy()
    changed.iloc[-1, changed.columns.get_loc("high")] = 10000
    assert indicators(changed).roc_event.iloc[-1]
    pd.testing.assert_frame_equal(indicators(f.iloc[:-1]), v.iloc[:-1])
