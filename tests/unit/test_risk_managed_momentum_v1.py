import pandas as pd
import pytest

from quant_lab.config import MarketConfig, StrategyConfig
from quant_lab.indicators import volatility_fractions
from quant_lab.strategies.risk_managed_momentum_v1 import RiskManagedMomentumV1Strategy


@pytest.mark.parametrize("side", [1, -1])
def test_momentum_and_structural_alignment_then_sign_exit(side):
    s = RiskManagedMomentumV1Strategy(
        StrategyConfig(
            name="risk_managed_momentum_v1", enabled=True, market=MarketConfig(timeframe="4h")
        )
    )
    f = pd.DataFrame(
        {
            "ready": [True] * 4,
            "momentum": [side, side, -side, 0],
            "close": [100 + side, 100 - side, 100 + side, 100 + side],
            "ema": [100] * 4,
        }
    )
    assert s._entries(f, side).tolist() == [True, False, False, False]
    assert s._exits(f, side).tolist() == [False, False, True, True]


@pytest.mark.parametrize("annual_bars", [2190, 365])
def test_inverse_volatility_reduces_exposure_and_zero_is_rejected(annual_bars):
    low = pd.Series([100 * (1.001 if i % 2 else 1.0) for i in range(30)])
    high = pd.Series([100 * (1.10 if i % 2 else 1.0) for i in range(30)])
    kw = dict(
        period=10, target_pct=10.0, minimum_pct=5.0, maximum_pct=25.0, annual_bars=annual_bars
    )
    assert volatility_fractions(low, **kw).iloc[-1] > volatility_fractions(high, **kw).iloc[-1]
    assert volatility_fractions(pd.Series([100.0] * 30), **kw).isna().all()
