from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_lab.config import MarketConfig, StrategyConfig
from quant_lab.indicators import realized_volatility, volatility_fractions
from quant_lab.lab_cli import main
from quant_lab.lab_rmm_falsification import concentration, frozen, validate, wf_summary
from quant_lab.strategies.risk_managed_momentum_v1 import RiskManagedMomentumV1Strategy

ROOT = Path(__file__).resolve().parents[2]


def test_frozen_protocol_candidates_neighbors_and_wf_no_selection():
    spec = frozen(ROOT)
    assert spec["central_parameters"] == dict(
        ema_period=200, momentum_lookback=180, volatility_period=180, target_volatility_pct=10.0
    )
    assert list(spec["candidates"]) == ["A", "B", "C", "D"]
    assert [
        p["strategy_parameters"]["momentum_lookback"][0] for p in spec["experiments"].values()
    ] == [180, 180, 150, 210]
    for plan in spec["experiments"].values():
        assert plan["modes"] == ["LONG_ONLY", "LONG_SHORT"]
        assert len(plan["validation"]["walk_forward"]) == 6
        assert all(len(v) == 1 for v in plan["strategy_parameters"].values())
        assert (
            plan["strategy_parameters"]["momentum_lookback"]
            == plan["strategy_parameters"]["volatility_period"]
        )
        previous = None
        for fold in plan["validation"]["walk_forward"]:
            assert fold["train"]["end"] <= fold["test"]["start"]
            assert fold["test"]["end"] <= plan["validation"]["test"]["start"]
            if previous:
                assert previous <= fold["test"]["start"]
            previous = fold["test"]["end"]
    assert validate(ROOT)["backtests"] == 704


@pytest.mark.parametrize("length", [0, 179, 181, 1000, 1020])
def test_actual_parameters_feature_signal_and_sizing_prefix_invariance(length):
    n = 1050
    times = pd.date_range("2020-01-01", periods=n, freq="4h", tz="UTC")
    prices = 100 * np.exp(0.08 * np.sin(np.arange(n) / 30) + np.arange(n) * 0.0001)
    candles = pd.DataFrame(
        dict(open=prices, high=prices + 1, low=prices - 1, close=prices, volume=1.0), index=times
    )
    strategy = RiskManagedMomentumV1Strategy(
        StrategyConfig(
            name="risk_managed_momentum_v1", enabled=True, market=MarketConfig(timeframe="4h")
        )
    )
    features = strategy.prepare_features(candles)
    prefix = strategy.prepare_features(candles.iloc[:length])
    pd.testing.assert_frame_equal(prefix, features.iloc[:length])
    assert (
        strategy.generate_signals(candles.iloc[:length]).long_entries
        == strategy.generate_signals(candles).long_entries[:length]
    )
    rv = realized_volatility(candles.close, 180, annual_bars=2190)
    pd.testing.assert_series_equal(
        rv.iloc[:length], realized_volatility(candles.close.iloc[:length], 180, annual_bars=2190)
    )
    if length > 180:
        assert features.momentum.iloc[-1] == pytest.approx(prices[-1] / prices[-181] - 1)


def test_volatility_formula_caps_floor_and_zero():
    returns = pd.Series([0.001, -0.001] * 100)
    close = (1 + returns).cumprod() * 100
    vol = realized_volatility(close, 180, annual_bars=2190)
    assert vol.iloc[-1] == pytest.approx(close.pct_change().iloc[-180:].std(ddof=1) * np.sqrt(2190))
    kwargs = dict(period=180, target_pct=10.0, minimum_pct=5.0, maximum_pct=25.0, annual_bars=2190)
    assert volatility_fractions(close, **kwargs).iloc[-1] == 0.25
    volatile = pd.Series([100.0, 200.0] * 100)
    assert volatility_fractions(volatile, **kwargs).iloc[-1] == 0.05
    assert volatility_fractions(pd.Series([100.0] * 200), **kwargs).isna().all()


def test_concentration_deletion_net_and_gross_denominators():
    c = concentration([100, 30, 20, -120])
    assert c["top_1_net_profit_share_pct"] == pytest.approx(100 / 30 * 100)
    assert c["top_3_gross_profit_share_pct"] == 100
    assert c["leave_top_1_out_pnl"] == -70
    assert c["leave_top_3_out_pnl"] == -120
    assert concentration([-5])["top_1_net_profit_share_pct"] is None
    assert concentration([])["worst_trade_pnl"] is None


def test_wf_summary_only_test_not_training():
    from quant_lab.lab_rmm_falsification import METRICS

    rows = []
    for i, value in enumerate((10.0, -4.0, 2.0)):
        rows.append(
            dict.fromkeys(METRICS, 1.0)
            | dict(
                candidate="A",
                variant="scaled_180",
                scenario="base",
                period=f"wf_{i}_test",
                return_pct=value,
            )
        )
    rows.append(rows[0] | dict(period="wf_0_train", return_pct=9999))
    result = wf_summary(pd.DataFrame(rows)).iloc[0]
    assert result.positive_folds == 2
    assert result.median_return_pct == 2
    assert result.worst_return_pct == -4
    assert result.best_return_pct == 10


def test_cli_read_only_validation(capsys):
    assert main(["--root", str(ROOT), "falsification", "validate"]) == 0
    assert '"backtests": 704' in capsys.readouterr().out
