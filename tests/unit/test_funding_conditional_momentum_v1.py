import pandas as pd
import pytest

from quant_lab.config import StrategyConfig
from quant_lab.strategies.funding_conditional_momentum_v1 import (
    FundingConditionalMomentumV1Strategy,
)


@pytest.mark.parametrize(
    "rate,momentum,case,side",
    [
        (-0.1, 1, "negative_positive", 1),
        (-0.1, -1, "negative_negative", -1),
        (0.1, -1, "positive_negative", -1),
        (0.1, 1, "positive_positive", 1),
    ],
)
def test_four_funding_cases_preserve_momentum_direction(rate, momentum, case, side):
    s = FundingConditionalMomentumV1Strategy(
        StrategyConfig(
            name="funding_conditional_momentum_v1",
            enabled=True,
            parameters={"momentum_lookback": 2, "atr_period": 2, "funding_window": 10},
        )
    )
    idx = pd.date_range("2020-01-01", periods=4, freq="h", tz="UTC")
    c = pd.DataFrame(
        {
            "open": [100, 100, 100, 100],
            "high": [102] * 4,
            "low": [98] * 4,
            "close": [100, 100, 100 + momentum, 100 + momentum],
            "volume": [1] * 4,
            "funding_rate": [rate] * 4,
            "funding_low": [-0.01] * 4,
            "funding_high": [0.01] * 4,
            "funding_percentile": [0.0] * 4,
            "funding_age_hours": [1.0] * 4,
        },
        index=idx,
    )
    f = s.prepare_features(c)
    assert f.conditional_case.iloc[-1] == case
    assert s._entries(f, side).iloc[-1]
    assert not s._entries(f, -side).iloc[-1]
    c["funding_age_hours"] = 9.0
    assert not s.generate_signals(c).long_entries[-1]
    assert not s.generate_signals(c).short_entries[-1]


def test_missing_observed_funding_is_explicit_failure():
    s = FundingConditionalMomentumV1Strategy(
        StrategyConfig(name="funding_conditional_momentum_v1", enabled=True)
    )
    c = pd.DataFrame(index=pd.DatetimeIndex([], tz="UTC"))
    with pytest.raises(ValueError, match="Observed causal funding"):
        s.prepare_features(c)
