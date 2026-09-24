from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_lab.batch_002 import Batch002Plan
from quant_lab.batch_003_analysis import monte_carlo, regimes, select_train
from quant_lab.config import StrategyConfig, load_research_config, load_yaml
from quant_lab.multitimeframe import completed_4h, confirmed_4h_features
from quant_lab.strategies.registry import StrategyRegistry


def candles(n=1700):
    rng = np.random.default_rng(93)
    close = 100 * np.exp(rng.normal(0.0003, 0.01, n).cumsum())
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 10.0},
        index=pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC"),
    )


@pytest.mark.parametrize(
    "name,params",
    [("ema_pullback", {"pullback_period": v}) for v in (20, 30, 50)]
    + [("mtf_momentum", {"breakout_hours": v}) for v in (24, 48, 72)]
    + [("atr_breakout", {"expansion_k": v}) for v in (1.0, 1.5, 2.0)]
    + [
        ("trend_strength", {"short_days": a, "long_days": b})
        for a, b in ((7, 30), (14, 30), (7, 60))
    ],
)
def test_every_variant_prefix_and_formulas(name, params):
    frame = candles()
    original = frame.copy()
    strategy = (
        StrategyRegistry()
        .discover()
        .create(StrategyConfig(name=name, enabled=True, parameters=params))
    )
    features = strategy.prepare_features(frame)
    signals = strategy.generate_signals(frame)
    for n in (1, 3, 4, 5, 199, 720, 799, 800, 801, 1440, 1441, 1601):
        pd.testing.assert_frame_equal(strategy.prepare_features(frame.iloc[:n]), features.iloc[:n])
        s = strategy.generate_signals(frame.iloc[:n])
        assert s.long_entries == signals.long_entries[:n]
        assert s.long_exits == signals.long_exits[:n]
    assert not any(signals.short_entries + signals.short_exits)
    pd.testing.assert_frame_equal(frame, original)
    if name == "trend_strength":
        period = params["long_days"] * 24
        assert features.roc_long.iloc[period] == pytest.approx(
            frame.close.iloc[period] / frame.close.iloc[0] - 1
        )
        assert features.prior_high.iloc[48] == frame.high.iloc[:48].max()
        assert features.ema50_prior.iloc[100] == features.ema50.iloc[76]
    if name == "atr_breakout":
        assert features.threshold.iloc[800] == pytest.approx(
            features.atr_ratio.iloc[80:800].quantile(0.6)
        )
        assert features.breakout_level.iloc[800] == pytest.approx(
            frame.close.iloc[799] + params["expansion_k"] * features.atr.iloc[799]
        )
    if name == "mtf_momentum":
        n = params["breakout_hours"]
        assert features.prior_high.iloc[n] == frame.high.iloc[:n].max()


def test_4h_partial_and_availability():
    f = candles(805)
    bars = completed_4h(f)
    assert len(bars) == 201
    first = bars.iloc[0]
    assert first.open == f.open.iloc[0] and first.close == f.close.iloc[3]
    assert first.high == f.high.iloc[:4].max() and first.low == f.low.iloc[:4].min()
    h = confirmed_4h_features(f)
    assert h.htf_close.iloc[:3].isna().all()
    assert h.htf_close.iloc[3:7].eq(f.close.iloc[3]).all()
    assert h.htf_ema200.iloc[:799].isna().all()
    assert h.htf_momentum.iloc[723] == pytest.approx(f.close.iloc[723] / f.close.iloc[3] - 1)
    assert (
        h.htf_available_at.dropna() <= h.htf_available_at.dropna().index + pd.Timedelta(hours=1)
    ).all()
    with pytest.raises(ValueError):
        completed_4h(f.drop(f.index[5]))
    assert len(completed_4h(f.iloc[1:8])) == 1


def test_train_selection_gates_and_ties():
    a = dict(
        candidate="a",
        partition="train",
        costs="base",
        return_pct=1.0,
        sharpe=1.0,
        profit_factor=1.1,
        closed_trades=40,
        max_drawdown_pct=10.0,
    )
    b = a | {"candidate": "b", "sharpe": 0.995, "max_drawdown_pct": 9.0}
    assert select_train([a, b], "a")["candidate"] == "b"
    assert select_train([a | {"closed_trades": 39}], "a")["diagnostic"] == "INSUFFICIENT_DATA"
    for change in (
        {"return_pct": 0},
        {"sharpe": 0},
        {"profit_factor": 1},
        {"max_drawdown_pct": 20},
    ):
        assert not select_train([a | change], "a")["train_eligible"]
    with pytest.raises(ValueError):
        select_train([a | {"partition": "final_holdout"}], "a")


def test_regime_prefix_and_mc_invariants():
    frame = candles()
    pd.testing.assert_frame_equal(regimes(frame.iloc[:1001]), regimes(frame).iloc[:1001])
    report, samples = monte_carlo([10.0, -9.0, -5.0, 2.0] * 10, "test", simulations=1000)
    again, other = monte_carlo([10.0, -9.0, -5.0, 2.0] * 10, "test", simulations=1000)
    assert report == again
    np.testing.assert_array_equal(samples, other)
    assert np.ptp(samples[:, 0]) == 0
    assert samples[0, 0] == pytest.approx(-0.2)
    assert monte_carlo([1.0] * 29, "short")[0]["status"] == "INSUFFICIENT_DATA"


def test_frozen_profile_loads_with_sufficient_context():
    root = Path("configs/profiles/batch_003")
    p = load_yaml(root / "batch.yaml", Batch002Plan)
    r = load_research_config(root / "app.yaml")
    assert len(r.strategies) == 4 and p.warmup_bars >= 1441
    assert p.train.end <= p.folds[0].test.start
    assert all(
        s.risk.max_position_pct == 25 and s.risk.risk_per_trade_pct == 0.5 for s in r.strategies
    )


def test_executor_synthetic_reconciles_regimes_and_artifacts(tmp_path):
    import json

    from quant_lab.batch import Candidate, Window
    from quant_lab.batch_003_execution import Batch003Executor
    from quant_lab.execution_config import ExecutionConfig
    from quant_lab.experiments import ExperimentStore
    from quant_lab.history import HistoryRequest

    f = candles(1800)
    history = HistoryRequest(
        start=f.index[1536].to_pydatetime(),
        end=(f.index[-1] + pd.Timedelta(hours=1)).to_pydatetime(),
        warmup_bars=1536,
    )
    config = load_research_config(Path("configs/profiles/batch_003/app.yaml"))
    store = ExperimentStore(tmp_path, {}, {})
    for folder in ("results", "equity", "trades"):
        (store.path / folder).mkdir()
    executor = Batch003Executor(
        store,
        config,
        load_yaml(Path("configs/profiles/batch_003/execution.yaml"), ExecutionConfig),
        StrategyRegistry().discover(),
    )
    for name in ("ema_pullback", "mtf_momentum", "atr_breakout", "trend_strength"):
        row = executor.execute(
            Candidate(id=name, strategy=name),
            f,
            history,
            Window(start=history.start, end=history.end),
            "train",
            "base",
            1536,
        )
        doc = json.loads((store.path / row["experiment_id"] / "result.json").read_text())
        for axis in doc["regimes"]["axes"].values():
            assert sum(r["bar_return_contribution_pct"] for r in axis.values()) == pytest.approx(
                row["return_pct"]
            )
            assert sum(r["trade_return_contribution_pct"] for r in axis.values()) == pytest.approx(
                row["return_pct"]
            )
