"""Quarter-hour accounting uses unchanged prices and exact real timestamps."""

import pandas as pd
import pytest

from quant_lab.config import CostsConfig, RiskConfig
from quant_lab.mtf_clock import execute, stretch


def market(n=8):
    idx = pd.date_range("2026-09-01", periods=n, freq="15min", tz="UTC")
    f = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0}, index=idx
    )
    d = pd.DataFrame(
        {"le": False, "se": False, "lx": False, "sx": False, "distance": 10.0}, index=idx
    )
    fund = pd.DataFrame({"rate": []}, index=pd.DatetimeIndex([], tz="UTC"))
    return f, d, fund


def run(f, d, fund, side="combined"):
    return execute(
        f,
        f,
        fund,
        d,
        f.index[0],
        f.index[-1] + pd.Timedelta(minutes=15),
        CostsConfig(trading_fee_pct=0.05, slippage_pct=0.02, spread_pct=0.01),
        RiskConfig(risk_per_trade_pct=0.5, take_profit_enabled=False, max_holding_bars=72),
        direction=side,
        timeframe="15m",
    )


@pytest.mark.parametrize("side,sign", [("long", 1), ("short", -1)])
@pytest.mark.parametrize("delay", [0, 1, 47])
def test_exact_funding_real_clock_and_direction(side, sign, delay):
    f, d, fund = market()
    d.loc[f.index[1], "le" if sign == 1 else "se"] = True
    d.loc[f.index[4], "lx" if sign == 1 else "sx"] = True
    stamp = f.index[2] + pd.Timedelta(milliseconds=delay)
    fund = pd.DataFrame({"rate": [0.001]}, index=pd.DatetimeIndex([stamp]))
    result, _, events = run(f, d, fund, side)
    (t,) = result.trades
    assert t.entry_time == f.index[1] and t.exit_time == f.index[4]
    assert t.funding_pnl == pytest.approx(-sign * t.quantity * 100 * 0.001)
    assert t.entry_fee == pytest.approx(t.entry_price * t.quantity * 0.0005)
    assert events[0]["time"] == stamp
    assert stretch(stretch(stamp, 4), 0.25) == stamp
    assert result.equity.iloc[-1] == pytest.approx(10000 + t.net_pnl)


def test_72_elapsed_hours_no_automatic_reversal():
    f, d, fund = market(300)
    d.loc[f.index[1], "le"] = True
    d.loc[f.index[2:290], "se"] = True
    result, _, _ = run(f, d, fund)
    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.reason == "time_stop"
    assert t.exit_time - t.entry_time == pd.Timedelta(hours=72)
    assert t.holding_bars == 288


def test_stop_on_real_quarter_bar():
    f, d, fund = market()
    d.loc[f.index[1], "le"] = True
    f.loc[f.index[2], "low"] = 80
    result, _, _ = run(f, d, fund, "long")
    (t,) = result.trades
    assert t.reason == "stop" and t.exit_bar_open == f.index[2]
