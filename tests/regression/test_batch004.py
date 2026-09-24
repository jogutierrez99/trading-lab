"""Independent formula, causal and protocol regressions, using synthetic data only."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_lab.batch import Candidate, Window
from quant_lab.batch_002 import Batch002Plan
from quant_lab.batch_004_analysis import cost_analysis, monte_carlo, select_train
from quant_lab.batch_004_execution import Batch004Executor
from quant_lab.batch_004_inventory import inventory
from quant_lab.config import StrategyConfig, load_research_config, load_yaml
from quant_lab.execution_config import ExecutionConfig
from quant_lab.experiments import ExperimentStore
from quant_lab.history import HistoryRequest
from quant_lab.strategies.registry import StrategyRegistry


def candles(n=1800):
    rng = np.random.default_rng(24)
    close = 100 * np.exp(rng.normal(0.0004, 0.012, n).cumsum())
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 10.0},
        index=pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC"),
    )


@pytest.mark.parametrize(
    "name,params",
    [("regime_trend", {"adx_threshold": v}) for v in (18, 22, 25)]
    + [
        ("dual_momentum", {"short_days": a, "long_days": b})
        for a, b in ((7, 30), (14, 60), (7, 60))
    ]
    + [("vol_expansion_trend", {"percentile_pct": v}) for v in (50, 60, 70)]
    + [("low_vol_pullback", {"percentile_pct": v}) for v in (30, 40, 50)],
)
def test_all_variants_causal_and_indicator_values(name, params):
    f = candles()
    original = f.copy()
    strategy = (
        StrategyRegistry()
        .discover()
        .create(StrategyConfig(name=name, enabled=True, parameters=params))
    )
    features, signals = strategy.prepare_features(f), strategy.generate_signals(f)
    for n in (1, 14, 27, 28, 200, 720, 734, 735, 800, 1440, 1441, 1601):
        pd.testing.assert_frame_equal(strategy.prepare_features(f.iloc[:n]), features.iloc[:n])
        partial = strategy.generate_signals(f.iloc[:n])
        assert partial.long_entries == signals.long_entries[:n]
        assert partial.long_exits == signals.long_exits[:n]
    pd.testing.assert_frame_equal(f, original)
    assert not any(signals.short_entries + signals.short_exits)
    expected = f.close.ewm(span=200, adjust=False, min_periods=200).mean()
    pd.testing.assert_series_equal(features.ema200, expected, check_names=False)
    if name == "dual_momentum":
        period = params["long_days"] * 24
        assert features.roc_long.iloc[period] == pytest.approx(
            f.close.iloc[period] / f.close.iloc[0] - 1
        )
        short = params["short_days"] * 24
        assert features.roc_short.iloc[short] == pytest.approx(
            f.close.iloc[short] / f.close.iloc[0] - 1
        )
        assert not any(signals.long_entries[:period])
    else:
        tr = pd.concat(
            [f.high - f.low, (f.high - f.close.shift(1)).abs(), (f.low - f.close.shift(1)).abs()],
            axis=1,
        ).max(axis=1)
        assert features.atr.iloc[800] == pytest.approx(tr.iloc[787:801].mean())
        assert features.atr_ratio.iloc[800] == pytest.approx(
            features.atr.iloc[800] / f.close.iloc[800]
        )
        q = params.get("percentile_pct", 40) / 100
        assert features.threshold.iloc[800] == pytest.approx(
            features.atr_ratio.iloc[80:800].quantile(q)
        )
        if name == "low_vol_pullback":
            assert features.exit_threshold.iloc[800] == pytest.approx(
                features.atr_ratio.iloc[80:800].quantile(0.7)
            )
            assert features.previous_touch.iloc[800] == (
                f.low.iloc[799] <= features.ema20.iloc[799]
            )
        else:
            n = 48 if name == "regime_trend" else 24
            assert features.prior_high.iloc[800] == f.high.iloc[800 - n : 800].max()
        if name == "vol_expansion_trend":
            assert features.ratio_sma24.iloc[800] == pytest.approx(
                features.atr_ratio.iloc[777:801].mean()
            )


def test_selection_exact_sharpe_ties_and_no_holdout():
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
    assert (
        select_train([a, a | {"candidate": "b", "sharpe": 0.999, "max_drawdown_pct": 1}], "a")[
            "candidate"
        ]
        == "a"
    )
    assert select_train([a, a | {"candidate": "b", "max_drawdown_pct": 9}], "a")["candidate"] == "b"
    for change in (
        {"return_pct": 0},
        {"sharpe": 0},
        {"profit_factor": 1},
        {"closed_trades": 39},
        {"max_drawdown_pct": 20},
    ):
        assert not select_train([a | change], "a")["train_eligible"]
    with pytest.raises(ValueError):
        select_train([a | {"partition": "final_holdout"}], "a")


def test_bootstrap_and_permutation_are_distinct_reproducible():
    pnl = [5.0, -10.0, 20.0, -4.0] * 10
    report, samples = monte_carlo(pnl, "test", simulations=1000)
    other, arrays = monte_carlo(pnl, "test", simulations=1000)
    assert report == other
    for key in samples:
        np.testing.assert_array_equal(samples[key], arrays[key])
    assert np.ptp(samples["reshuffling"][:, 0]) == 0
    assert samples["reshuffling"][0, 3] == sum(pnl)
    assert np.ptp(samples["bootstrap"][:, 0]) > 0
    assert report["methods"]["bootstrap"]["seed"] != report["methods"]["reshuffling"]["seed"]
    assert monte_carlo([1.0] * 29, "short")[0]["status"] == "INSUFFICIENT_DATA"


def test_inventory_detects_new_csv_and_eth_without_network(tmp_path):
    root = tmp_path / "data/csv"
    root.mkdir(parents=True)
    assert inventory(tmp_path)["decision"] == "REUSED_HISTORY_DIAGNOSTIC"
    pd.DataFrame([int(pd.Timestamp("2026-02-01", tz="UTC").timestamp() * 1000)]).to_csv(
        root / "BTCUSDT-1h-2026-02.csv", index=False, header=False
    )
    result = inventory(tmp_path)
    assert result["fresh_or_eth_available"]
    pd.DataFrame([int(pd.Timestamp("2025-01-01", tz="UTC").timestamp() * 1e6)]).to_csv(
        root / "ETHUSDT-1h-2025-01.csv", index=False, header=False
    )
    assert any(r["is_eth"] for r in inventory(tmp_path)["csv_files"])


def test_new_executor_and_profile_reconcile(tmp_path):
    import json

    root = Path("configs/profiles/batch_004")
    config = load_research_config(root / "app.yaml")
    plan = load_yaml(root / "batch.yaml", Batch002Plan)
    execution = load_yaml(root / "execution.yaml", ExecutionConfig)
    assert plan.train.end <= plan.folds[0].test.start
    assert len(plan.candidates) == 12 and plan.warmup_bars == 1536
    f = candles()
    h = HistoryRequest(
        start=f.index[1536].to_pydatetime(),
        end=(f.index[-1] + pd.Timedelta(hours=1)).to_pydatetime(),
        warmup_bars=1536,
    )
    store = ExperimentStore(tmp_path, {}, {})
    for folder in ("results", "trades", "equity"):
        (store.path / folder).mkdir()
    executor = Batch004Executor(store, config, execution, StrategyRegistry().discover())
    for c in plan.candidates:
        row = executor.execute(c, f, h, Window(start=h.start, end=h.end), "train", "base", 1536)
        d = json.loads((store.path / row["experiment_id"] / "result.json").read_text())
        assert not d["open_position"]
        for axis in d["regimes"]["axes"].values():
            assert sum(r["gross_pnl"] for r in axis.values()) == pytest.approx(row["gross_pnl"])
            assert sum(r["bar_return_contribution_pct"] for r in axis.values()) == pytest.approx(
                row["return_pct"]
            )
    # Costs must be complete independent scenarios; do not derive fills by subtracting fees.
    with pytest.raises(ValueError):
        cost_analysis(executor.rows, {"regime_trend": {"candidate": "regime_trend_a18"}})
    assert Candidate(id="smoke", strategy="dual_momentum").strategy == "dual_momentum"


def test_preflight_rejects_failed_checks_or_changed_code(tmp_path):
    import json

    from quant_lab.batch_004 import check_preflight

    folder = tmp_path / "reports/batch_004"
    folder.mkdir(parents=True)
    record = {
        c: {"exit_code": 0}
        for c in ("pytest -q", "ruff check .", "ruff format --check .", "pip check")
    }
    record["code_sha256"] = "frozen"
    path = folder / "preflight.json"
    path.write_text(json.dumps(record))
    check_preflight(tmp_path, "frozen")
    with pytest.raises(ValueError, match="Code changed"):
        check_preflight(tmp_path, "changed")
    record["pytest -q"]["exit_code"] = 1
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="not successful"):
        check_preflight(tmp_path, "frozen")
