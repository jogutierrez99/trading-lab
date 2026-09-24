"""State transitions, independent price diagnostics and actual structural execution."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_lab.backtest import BacktestResult
from quant_lab.batch import Window
from quant_lab.batch_002 import Batch002Plan
from quant_lab.batch_005_execution import Batch005Executor
from quant_lab.config import StrategyConfig, load_research_config, load_yaml
from quant_lab.entry_diagnostics import entry_diagnostics
from quant_lab.execution_config import ExecutionConfig
from quant_lab.experiments import ExperimentStore
from quant_lab.history import HistoryRequest
from quant_lab.setup_states import channel_retest, rsi_reset
from quant_lab.strategies.base import Signals
from quant_lab.strategies.registry import StrategyRegistry
from quant_lab.structural_execution import run_structural


def candles(n=1800):
    rng = np.random.default_rng(51)
    close = 100 * np.exp(rng.normal(0.0004, 0.013, n).cumsum())
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 10.0},
        index=pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC"),
    )


@pytest.mark.parametrize(
    "name,params",
    [("channel_break_retest", {"channel_hours": v}) for v in (24, 48, 72)]
    + [("trend_acceleration", {"fast_hours": v}) for v in (12, 24, 48)]
    + [("rsi_momentum_reset", {"reset_threshold": v}) for v in (40, 35, 30)]
    + [("vol_contraction_expansion", {"contraction_bars": v}) for v in (6, 12, 18)],
)
def test_every_variant_prefix_and_formulas(name, params):
    f = candles()
    strategy = (
        StrategyRegistry()
        .discover()
        .create(StrategyConfig(name=name, enabled=True, parameters=params))
    )
    features, signals = strategy.prepare_features(f), strategy.generate_signals(f)
    for n in (1, 14, 200, 272, 720, 734, 758, 800, 1001, 1601):
        pd.testing.assert_frame_equal(strategy.prepare_features(f.iloc[:n]), features.iloc[:n])
        partial = strategy.generate_signals(f.iloc[:n])
        assert partial.long_entries == signals.long_entries[:n]
        assert partial.long_exits == signals.long_exits[:n]
    assert not any(signals.short_entries + signals.short_exits)
    if name == "trend_acceleration":
        assert features.slope_fast.iloc[800] == pytest.approx(
            features.ema50.iloc[800] / features.ema50.iloc[800 - params["fast_hours"]] - 1
        )
        assert features.slope_slow.iloc[800] == pytest.approx(
            features.ema200.iloc[800] / features.ema200.iloc[728] - 1
        )
        assert features.previous_slope_fast.iloc[800] == features.slope_fast.iloc[776]
    if name == "rsi_momentum_reset":
        assert features.roc30.iloc[800] == pytest.approx(f.close.iloc[800] / f.close.iloc[80] - 1)
    if name == "vol_contraction_expansion":
        assert features.p30.iloc[800] == pytest.approx(
            features.atr_ratio.iloc[80:800].quantile(0.3)
        )
        assert features.p50.iloc[800] == pytest.approx(
            features.atr_ratio.iloc[80:800].quantile(0.5)
        )
        assert features.recent_contractions.iloc[800] == features.contraction.iloc[776:800].sum()
    if "prior_high" in features:
        n = params.get("channel_hours", 24)
        assert features.prior_high.iloc[800] == f.high.iloc[800 - n : 800].max()


def channel_frame(n):
    return pd.DataFrame(
        {
            "close": [102.0] * n,
            "high": [103.0] * n,
            "low": [101.0] * n,
            "ema50": [99.0] * n,
            "ema200": [98.0] * n,
            "atr": [2.0] * n,
            "prior_high": [100.0] * n,
        }
    )


def test_channel_first_retest_frozen_level_later_confirmation_and_cancel():
    f = channel_frame(5)
    f.loc[1, ["low", "close", "high"]] = [100.4, 102.0, 103.0]
    f.loc[2, "close"] = 104.0
    out = channel_retest(f)
    assert out.setup_phase.tolist()[:3] == ["breakout", "retested", "confirmed"]
    assert out.entry.tolist()[:3] == [False, False, True]
    assert out.stop_anchor.iloc[2] == pytest.approx(100.4 - 0.02)
    # Newly computed channel/ATR cannot move the frozen breakout zone.
    f.loc[1, "prior_high"] = 500.0
    f.loc[1, "atr"] = 20.0
    assert channel_retest(f).entry.iloc[2]
    f.loc[2, "close"] = 97.0
    assert channel_retest(f).setup_phase.iloc[2] == "cancelled_trend"
    assert not channel_retest(f).entry.iloc[2]


def test_channel_retest_expiry_boundary_and_confirmation_wait():
    f = channel_frame(30)
    f.loc[24, "low"] = 100.0
    f.loc[26, "close"] = 104.0
    out = channel_retest(f)
    assert out.setup_phase.iloc[24] == "retested" and out.entry.iloc[26]
    f.loc[24, "low"] = 101.0
    f.loc[25, "low"] = 100.0
    assert channel_retest(f).setup_phase.iloc[25] == "expired_retest"
    assert not channel_retest(f).entry.iloc[26]


def reset_frame(values):
    n = len(values)
    return pd.DataFrame(
        {
            "rsi": values,
            "close": [110.0] * n,
            "ema50": [105.0] * n,
            "ema200": [100.0] * n,
            "roc30": [0.1] * n,
        }
    )


def test_rsi_cross_consumption_no_refresh_and_expiry():
    assert rsi_reset(reset_frame([45, 39, 45, 51, 49, 51]), 40).entry.tolist() == [
        False,
        False,
        False,
        True,
        False,
        False,
    ]
    assert rsi_reset(reset_frame([45, 39] + [45] * 47 + [51]), 40).entry.iloc[-1]
    assert not rsi_reset(reset_frame([45, 39] + [45] * 48 + [51]), 40).entry.iloc[-1]
    values = [45, 39] + [45] * 30 + [39] + [45] * 17 + [51]
    assert not rsi_reset(reset_frame(values), 40).entry.iloc[-1]
    f = reset_frame([45, 39, 51])
    f.loc[1, "roc30"] = -0.1
    assert not rsi_reset(f, 40).entry.any()


def structural_fixture(opening=101.0):
    f = candles(5)
    f.loc[:, ["open", "high", "low", "close"]] = [100.0, 102.0, 99.0, 101.0]
    f.loc[f.index[1], ["open", "high", "low", "close"]] = [
        opening,
        max(opening, 103.0),
        min(opening, 100.0),
        max(opening, 102.0),
    ]
    h = HistoryRequest(
        start=f.index[0].to_pydatetime(),
        end=(f.index[-1] + pd.Timedelta(hours=1)).to_pydatetime(),
        warmup_bars=0,
    )
    r = load_research_config(Path("configs/profiles/batch_005/app.yaml"))
    risk = next(s.risk for s in r.strategies if s.name == "channel_break_retest")
    execution = load_yaml(Path("configs/profiles/batch_005/execution.yaml"), ExecutionConfig)
    signals = Signals((True, False, False, False, False), (False,) * 5, (False,) * 5, (False,) * 5)
    anchors = pd.Series([99.0, np.nan, np.nan, np.nan, np.nan], index=f.index)
    atrs = pd.Series(2.0, index=f.index)
    return f, h, r, risk, execution, signals, anchors, atrs


def test_absolute_stop_gap_rejection_and_sizing():
    f, h, r, risk, ex, s, a, atr = structural_fixture()
    result = run_structural(f, s, a, atr, h, r.app, risk, ex)
    t = result.trades[0]
    assert t.stop == pytest.approx(99.0)
    assert t.entry_time == f.index[1] and t.signal_close == f.index[1]
    assert t.expected_stop_loss <= 50.0 and t.quantity * t.entry_price + t.entry_fee <= 2500.0
    assert not result.open_position
    assert result.equity.iloc[-1] == pytest.approx(10000 + sum(t.net_pnl for t in result.trades))
    for opening, reason in (
        (98.0, "open_at_or_below_structural_stop"),
        (110.0, "structural_distance_exceeds_atr_cap"),
    ):
        f, h, r, risk, ex, s, a, atr = structural_fixture(opening)
        result = run_structural(f, s, a, atr, h, r.app, risk, ex)
        assert not result.trades
        assert result.rejections[0].reason == reason


def test_excursions_open_intrabar_close_and_horizon_censoring():
    f, h, r, risk, ex, s, a, atr = structural_fixture()
    result = run_structural(f, s, a, atr, h, r.app, risk, ex)
    t = result.trades[0]
    prices = candles(80)
    prices.loc[:, ["open", "high", "low", "close"]] = [100.0, 110.0, 90.0, 105.0]
    equity = pd.Series([10000.0, 10001.0], index=[prices.index[0], prices.index[20]])
    t = replace(
        t,
        entry_time=prices.index[0],
        entry_reference=100.0,
        exit_bar_open=prices.index[1],
        exit_reference=99.0,
        exit_timing="open",
    )
    fake = BacktestResult((t,), equity, (), None, "long", "spot", equity * 0, 0.0)
    q, e, _ = entry_diagnostics(prices, fake)
    assert q["trades"][0]["mfe_pct"] == pytest.approx(10.0)
    assert q["trades"][0]["mae_pct"] == pytest.approx(10.0)
    assert e["summary"]["6"]["mean"] == pytest.approx(5.0)
    assert e["summary"]["24"]["n"] == 0 and e["summary"]["24"]["censored"] == 1
    t = replace(t, exit_bar_open=prices.index[0], exit_timing="intrabar", exit_reference=98.0)
    q, _, _ = entry_diagnostics(prices, replace(fake, trades=(t,)))
    x = q["trades"][0]
    assert x["mfe_pct"] == 0 and x["mae_pct"] == pytest.approx(2.0)
    assert x["mfe_upper_bound_pct"] == pytest.approx(10.0) and x[
        "mae_upper_bound_pct"
    ] == pytest.approx(10.0)
    assert x["time_to_mae_hours_lower"] == 0 and x["time_to_mae_hours_upper"] == 1
    t = replace(t, exit_timing="close", exit_reference=105.0)
    q, _, _ = entry_diagnostics(prices, replace(fake, trades=(t,)))
    assert q["trades"][0]["mfe_pct"] == pytest.approx(10.0)
    assert not q["trades"][0]["intrabar_censored"]


def test_profile_real_executor_all_variants(tmp_path):
    root = Path("configs/profiles/batch_005")
    plan = load_yaml(root / "batch.yaml", Batch002Plan)
    r = load_research_config(root / "app.yaml")
    ex = load_yaml(root / "execution.yaml", ExecutionConfig)
    store = ExperimentStore(tmp_path, {}, {})
    for folder in ("results", "trades", "equity"):
        (store.path / folder).mkdir()
    executor = Batch005Executor(store, r, ex, StrategyRegistry().discover())
    f = candles()
    h = HistoryRequest(
        start=f.index[1536].to_pydatetime(),
        end=(f.index[-1] + pd.Timedelta(hours=1)).to_pydatetime(),
        warmup_bars=1536,
    )
    for c in plan.candidates:
        row = executor.execute(c, f, h, Window(start=h.start, end=h.end), "train", "base", 1536)
        assert row["has_open_position"] is False
        assert row["mfe_mae_ratio"] is None or row["mfe_mae_ratio"] >= 0
    # Ordinary legacy runner must not silently replace a structure stop with an ATR stop.
    from quant_lab.batch import resolve_candidate
    from quant_lab.research_run import run_strategy

    channel = next(c for c in plan.candidates if c.strategy == "channel_break_retest")
    with pytest.raises(ValueError, match="ATR stops only"):
        run_strategy(
            f, h, resolve_candidate(r, channel), channel.strategy, ex, StrategyRegistry().discover()
        )


def test_structural_entry_ignores_future_high_low_close():
    f, h, r, risk, ex, s, a, atr = structural_fixture()
    first = run_structural(f, s, a, atr, h, r.app, risk, ex).trades[0]
    altered = f.copy()
    altered.loc[f.index[1] :, "high"] = 200.0
    altered.loc[f.index[1] :, "low"] = 1.0
    altered.loc[f.index[1] :, "close"] = 150.0
    second = run_structural(altered, s, a, atr, h, r.app, risk, ex).trades[0]
    assert first.entry_price == second.entry_price
    assert first.quantity == second.quantity
    assert first.stop == second.stop
