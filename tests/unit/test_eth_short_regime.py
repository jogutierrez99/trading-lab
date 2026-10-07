"""Causal labels, unchanged grids and tiny synthetic audited/publication workflow."""

import copy
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from test_lab import lab as lab_fixture
from test_lab_research_workflow import fingerprint
from test_trend_volatility_breakout_v1 import candles

from quant_lab.config import StrategyConfig
from quant_lab.eth_short_regimes import (
    outlier_rows,
    pnl_statistics,
    regime_features,
    regime_rows,
    tag_trades,
)
from quant_lab.history import HistoryRequest
from quant_lab.history_cache import save_bundle
from quant_lab.lab_eth_short_regime import (
    EXPERIMENTS,
    EXPORTS,
    FAMILIES,
    LOCK,
    WARNING,
    check_lock,
    publish,
    report,
    run_study,
    validate,
    walk_forward_summary,
)
from quant_lab.lab_evidence import sha256
from quant_lab.lab_runner import run
from quant_lab.lab_schema import resolve
from quant_lab.lab_trend_expansion import main
from quant_lab.strategies.registry import StrategyRegistry

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def sources(tmp_path):
    root, _, base, frame = lab_fixture.__wrapped__(tmp_path)
    request = HistoryRequest(
        symbol="ETH/USDT",
        start=datetime(2022, 1, 2, tzinfo=UTC),
        end=datetime(2022, 1, 18, tzinfo=UTC),
        warmup_bars=24,
    )
    bundle = save_bundle(root / "data", frame, request, [])
    registry = StrategyRegistry().discover()
    plans, hashes = [], {}
    for family, identity, strategy in zip(
        FAMILIES,
        EXPERIMENTS,
        ("atr_volatility_breakout", "donchian_atr_breakout", "donchian_trend_breakout"),
        strict=True,
    ):
        params = registry.implementation(strategy).parameter_model().model_dump()
        params.update(trend_length=10, slope_lookback=2, atr_length=3, exit_length=3)
        if "fast_length" in params:
            params["fast_length"] = 3
        if "breakout_length" in params:
            params["breakout_length"] = 3
        config = StrategyConfig(name=strategy, enabled=True, parameters=params)
        profile = root / "configs" / (family + ".yaml")
        profile.write_text(yaml.safe_dump(config.model_dump()), encoding="utf-8")
        raw = copy.deepcopy(base)
        raw.update(
            experiment_id=identity,
            strategy=dict(id=strategy, config="../" + profile.name),
            strategy_parameters={},
            modes=["SHORT_ONLY"],
            markets=[
                dict(
                    symbol="ETHUSDT",
                    timeframe="1h",
                    dataset="../../data/" + bundle.name,
                    warmup_bars=250,
                )
            ],
        )
        raw["execution"]["market_mode"] = "synthetic"

        def period(day):
            return datetime(2022, 1, day, tzinfo=UTC)

        raw["validation"]["train"] = dict(start=period(12), end=period(13))
        raw["validation"]["validation"] = dict(start=period(13), end=period(17))
        raw["validation"]["test"] = dict(start=period(17), end=period(18))
        raw["validation"]["walk_forward"] = [
            dict(
                train=dict(start=period(12), end=period(day)),
                test=dict(start=period(day), end=period(day + 1)),
            )
            for day in (13, 14, 15, 16)
        ]
        raw["diagnostic_periods"] = {
            "diagnostic_partial_year": dict(start=period(12), end=period(18))
        }
        path = root / "configs/experiments" / (identity + ".yaml")
        path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        for file in (path, profile):
            hashes[file.relative_to(root).as_posix()] = sha256(file)
        plans.append(resolve(path.parent, identity))
    lock = yaml.safe_load((ROOT / LOCK).read_text())
    lock["file_sha256"] = hashes
    (root / LOCK).parent.mkdir(parents=True)
    (root / LOCK).write_text(yaml.safe_dump(lock), encoding="utf-8")
    outputs = [run(path, exp, root) for path, exp in plans]
    return root, outputs


def test_causal_prefix_future_mutation_gap_and_alignment():
    frame = candles(1200)
    full = regime_features(frame)
    pd.testing.assert_frame_equal(full.iloc[:700], regime_features(frame.iloc[:700]))
    changed = frame.copy()
    changed.iloc[700:, :4] *= 100
    pd.testing.assert_frame_equal(full.iloc[:700], regime_features(changed).iloc[:700])
    gap = frame.drop(frame.index[600:650])
    after = gap.loc[gap.index >= frame.index[650]]
    pd.testing.assert_frame_equal(regime_features(gap).loc[after.index], regime_features(after))
    assert regime_features(after).trend.iloc[:204].eq("unavailable").all()
    with pytest.raises(ValueError, match="UTC"):
        regime_features(frame.iloc[::-1])
    with pytest.raises(ValueError, match="UTC"):
        regime_features(frame.set_axis(frame.index.tz_localize(None)))


def test_close_timestamp_uses_signal_candle_not_next_open():
    index = pd.date_range("2024-01-01", periods=2, freq="h", tz="UTC")
    features = pd.DataFrame(
        dict(trend=["bearish", "bullish"], volatility=["high", "ordinary"]), index=index
    )
    trade = dict(side="short", signal_close=index[1].isoformat(), net_pnl=1.0)
    assert tag_trades([trade], features)[0]["trend"] == "bearish"
    assert tag_trades([trade], features)[0]["volatility"] == "high"
    with pytest.raises(ValueError, match="non-short"):
        tag_trades([trade | dict(side="long")], features)
    with pytest.raises(ValueError, match="missing"):
        tag_trades([trade | dict(signal_close=(index[0]).isoformat())], features)


def test_buckets_partition_each_dimension_and_sample_and_outliers():
    trades = [
        dict(net_pnl=v, trend="bearish", volatility="high") for v in [-1.0] * 98 + [50.0, 150.0]
    ]
    rows = regime_rows({}, trades)
    for dimension in ("trend", "volatility", "combined"):
        subset = [r for r in rows if r["dimension"] == dimension]
        assert sum(r["closed_trades"] for r in subset) == 100
        assert sum(r["net_pnl"] for r in subset) == 102
    assert pnl_statistics([1.0, 2.0, 3.0])["sample_status"] == "INSUFFICIENT_SAMPLE"
    assert pnl_statistics([])["profit_factor"] is None
    outliers = outlier_rows({}, trades)
    assert outliers[0]["net_pnl"] == 102
    assert outliers[1]["net_pnl"] == -48
    assert outliers[2]["removed_trades"] == 5
    assert outliers[3]["removed_trades"] == 10
    assert outlier_rows({}, [dict(net_pnl=-2.0)])[1]["closed_trades"] == 0


def test_frozen_repository_grids_periods_costs_and_scope():
    check_lock(ROOT)
    for family, name in zip(FAMILIES, EXPERIMENTS, strict=True):
        _, current = resolve(ROOT / "configs/experiments", name)
        _, previous = resolve(ROOT / "configs/experiments", f"trend_expansion_entry_{family}_v1")
        assert current.strategy_parameters == previous.strategy_parameters
        assert current.validation == previous.validation
        assert current.costs == previous.costs and current.execution == previous.execution
        assert current.markets == [m for m in previous.markets if m.symbol == "ETHUSDT"]
        assert current.modes == ["SHORT_ONLY"]
        assert list(current.diagnostic_periods) == [
            f"diagnostic_year_{y}" for y in range(2023, 2027)
        ]
    assert sha256(ROOT / "src/quant_lab/lab_cli.py") == (
        "a9bd82660446cea7a176110ffe73baac6c00bac25437eb921b68ae0fb60368f7"
    )


def test_synthetic_report_publish_immutable_and_cli(sources, monkeypatch):
    root, runs = sources
    before = [fingerprint(p) for p in runs]
    monkeypatch.setattr("quant_lab.lab_runner.evaluate", lambda *a: pytest.fail("No simulation"))
    assert validate(root, full=True)["backtests_executed"] == 0
    directory = report(root, [p.name for p in runs])
    summary = pd.read_csv(directory / "summary.csv")
    regimes = pd.read_csv(directory / "regime_comparison.csv")
    assert summary.symbol.eq("ETHUSDT").all() and summary["mode"].eq("SHORT_ONLY").all()
    assert len(regimes) == len(summary) * 19
    assert pd.read_csv(directory / "walk_forward_summary.csv").folds.eq(4).all()
    assert WARNING in (directory / "conclusions.md").read_text()
    result = publish(root, directory.name)
    destination = Path(result["publication_directory"])
    assert set(result["published"]) == set(EXPORTS) | {"metadata.json"}
    assert str(root) not in (destination / "sources.json").read_text()
    assert not list(destination.glob("*.parquet"))
    assert before == [fingerprint(p) for p in runs]
    assert main(["--root", str(root), "eth-short-regime", "validate"]) == 0
    with pytest.raises(FileExistsError):
        publish(root, directory.name)
    with pytest.raises(ValueError, match="file limit"):
        publish(root, directory.name, max_bytes=1)
    path, experiment = resolve(root / "configs/experiments", EXPERIMENTS[0])
    data = (path.parent / experiment.markets[0].dataset / "candles.parquet").resolve()
    original = data.read_bytes()
    data.write_bytes(original + b"tampered")
    with pytest.raises(ValueError, match="dataset changed"):
        publish(root, directory.name)
    data.write_bytes(original)
    (directory / "summary.csv").write_text("tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        publish(root, directory.name)


def test_reject_changed_sources_and_wrong_order(sources):
    root, runs = sources
    with pytest.raises(ValueError, match="order"):
        report(root, [p.name for p in reversed(runs)])
    path = root / f"configs/experiments/{EXPERIMENTS[0]}.yaml"
    path.write_text(path.read_text() + "\n# changed\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        validate(root)


def test_run_command_preflights_all_then_executes_exact_three(sources, monkeypatch):
    root, _ = sources
    calls = []
    monkeypatch.setattr(
        "quant_lab.lab_eth_short_regime.run",
        lambda path, exp, root: calls.append(exp.experiment_id) or path,
    )
    assert len(run_study(root)["run_directories"]) == 3
    assert calls == list(EXPERIMENTS)
    calls.clear()
    path = root / f"configs/experiments/{EXPERIMENTS[-1]}.yaml"
    path.write_text(path.read_text() + "\n# changed\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        run_study(root)
    assert not calls


def test_walk_forward_separates_adaptive_policy_and_missing_pf():
    frame = pd.DataFrame(
        [
            dict(
                family="atr",
                scenario="adverse",
                period=f"wf_{i}_test",
                return_pct=v,
                expectancy=v,
                profit_factor=np.nan if i == 0 else 1.1,
                closed_trades=3 if i == 0 else 30,
                configuration_id=str(i),
            )
            for i, v in enumerate([1.0, 2.0, -1.0, 0.0])
        ]
    )
    row = walk_forward_summary(frame).iloc[0]
    assert row.profitable_ratio == "2/4" and row.negative_folds == 1 and row.zero_folds == 1
    assert row.insufficient_sample_folds == row.undefined_profit_factor_folds == 1
    assert "not evidence for each fixed candidate" in row.selection
    with pytest.raises(ValueError, match="four distinct"):
        walk_forward_summary(frame.iloc[:3])
