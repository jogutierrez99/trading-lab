"""Small synthetic orchestration/fills only; never run the research grids."""

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from quant_lab.config import load_yaml
from quant_lab.lab_cli import main
from quant_lab.lab_comparison import compare
from quant_lab.lab_data import load_bundle
from quant_lab.lab_runner import evaluate, parameter_risk, prepare, run
from quant_lab.lab_schema import Experiment
from quant_lab.mtf_data import quarter_audit
from quant_lab.study_data import HOURS

ROOT = Path(__file__).resolve().parents[2]
NAMES = [
    "trend_rsi_pullback_" + s for s in ("video_reference", "v1_single_tf", "v1_mtf", "v1_mtf_slope")
]


@pytest.fixture
def small(tmp_path):
    (tmp_path / "configs/experiments").mkdir(parents=True)
    (tmp_path / "configs/profiles").mkdir()
    for name in ("app.yaml", "risk.yaml"):
        shutil.copyfile(ROOT / "configs" / name, tmp_path / "configs" / name)
    shutil.copyfile(
        ROOT / "configs/profiles/lab_trend_rsi_pullback.yaml",
        tmp_path / "configs/profiles/lab_trend_rsi_pullback.yaml",
    )
    shutil.copyfile(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    n = 1400
    price = 100 + np.arange(n) * 0.1
    price[-10:] -= np.arange(10) * 0.9
    frame = pd.DataFrame(
        {"open": price, "high": price + 0.2, "low": price - 0.2, "close": price, "volume": 10.0},
        index=pd.date_range("2022-01-01", periods=n, freq="15min", tz="UTC"),
    )
    directory = tmp_path / "data/quarters"
    directory.mkdir(parents=True)
    frame.to_parquet(directory / "data.parquet")
    manifest = {
        "audit": quarter_audit(frame, "BTCUSDT"),
        "sha256": hashlib.sha256((directory / "data.parquet").read_bytes()).hexdigest(),
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    raw = yaml.safe_load((ROOT / "configs/experiments" / (NAMES[0] + ".yaml")).read_text())
    raw["markets"] = [
        raw["markets"][0]
        | {"dataset": "../../data/quarters", "dataset_id": manifest["audit"]["hash"]}
    ]
    points = [frame.index[i].to_pydatetime() for i in (1004, 1104, 1204)] + [
        (frame.index[-1] + pd.Timedelta(minutes=15)).to_pydatetime()
    ]
    raw["validation"] = {
        label: {"start": points[i], "end": points[i + 1]}
        for i, label in enumerate(("train", "validation", "test"))
    }
    return tmp_path, raw, frame


def save(root, raw):
    path = root / "configs/experiments" / (raw["experiment_id"] + ".yaml")
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path, Experiment.model_validate(raw)


def test_exact_research_grids_and_long_temporal_protocol():
    original = load_yaml(ROOT / "configs/experiments/trend_btc_1h_001.yaml", Experiment)
    batch = yaml.safe_load((ROOT / "configs/profiles/batch_003/batch.yaml").read_text())
    expected_periods = [
        ("2023-06-04", "2024-07-01"),
        ("2024-07-01", "2025-01-01"),
        ("2025-07-01", "2026-09-26"),
        ("2023-07-01", "2024-07-01"),
        ("2024-07-01", "2024-10-01"),
        ("2023-10-01", "2024-10-01"),
        ("2024-10-01", "2025-01-01"),
        ("2024-01-01", "2025-01-01"),
        ("2025-01-01", "2025-04-01"),
        ("2024-04-01", "2025-04-01"),
        ("2025-04-01", "2025-07-01"),
    ]
    assert HOURS == {
        "1h": 1,
        "4h": 4,
        "1d": 24,
    }  # Do not expand historical download/study matrices.
    for name in NAMES:
        path = ROOT / "configs/experiments" / (name + ".yaml")
        exp = load_yaml(path, Experiment)
        context = prepare(path, exp)
        expected = 1 if name == NAMES[0] else 486
        assert exp.combinations == len(context["parameters"]) == expected
        # All candidates in three main periods and four WF trains; one winner per WF test.
        assert context["backtests"] == 2 * 3 * 2 * (expected * (3 + 4) + 4)
        assert [(p.start, p.end) for _, p in exp.validation.periods()] == [
            (pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"))
            for start, end in expected_periods
        ]
        folds = exp.validation.walk_forward
        assert len(folds) == 4
        assert [f.model_dump() for f in folds] == batch["folds"]
        assert all(f.train.end <= f.test.start for f in folds)
        assert all(a.test.end <= b.test.start for a, b in zip(folds[:-1], folds[1:], strict=True))
        assert all(f.test.end <= exp.validation.test.start for f in folds)
        assert folds[-1].test.end == exp.validation.test.start
        assert exp.validation.causal() is exp.validation
        assert exp.filters == original.filters
        assert exp.validation.cost_stress == original.validation.cost_stress
        assert exp.costs == original.costs and exp.initial_cash == original.initial_cash
        assert exp.app == original.app
        assert exp.execution.market_mode == "synthetic"
        assert exp.execution.model_dump(exclude={"market_mode", "filter_assumption"}) == (
            original.execution.model_dump(exclude={"market_mode", "filter_assumption"})
        )
        assert "rsi_overbought" not in exp.strategy_parameters
        assert all(p["rsi_overbought"] == 100 - p["rsi_oversold"] for p in context["parameters"])
        assert all(p["sma_slope_lookback"] == 5 for p in context["parameters"])


@pytest.mark.parametrize("mode", ["LONG_ONLY", "SHORT_ONLY", "LONG_SHORT"])
def test_next_open_atr_stop_and_reward_risk(small, mode):
    root, raw, frame = small
    if mode == "SHORT_ONLY":
        flipped = frame.copy()
        flipped["open"], flipped["close"] = 500 - frame.open, 500 - frame.close
        flipped["high"], flipped["low"] = 500 - frame.low, 500 - frame.high
        frame = flipped
    path, exp = save(root, raw)
    context = prepare(path, exp)
    context["execution"] = exp.execution
    params = context["parameters"][0] | {
        "atr_length": 20,
        "atr_multiplier": 2.5,
        "reward_risk": 1.25,
    }
    result = evaluate(
        context, frame, exp.markets[0], mode, params, exp.validation.test, context["app"].costs
    )
    assert result.trades
    from quant_lab.features import atr

    distances = atr(frame, 20) * 2.5
    for t in result.trades:
        previous = t.entry_time - pd.Timedelta(minutes=15)
        side = 1 if t.side == "long" else -1
        assert t.entry_time == t.signal_close and t.entry_time > previous
        assert t.entry_reference == frame.loc[t.entry_time, "open"]
        assert t.stop == pytest.approx(t.entry_price - side * distances.loc[previous])
        assert t.target == pytest.approx(t.entry_price + side * distances.loc[previous] * 1.25)
        assert t.entry_fee > 0 and t.exit_fee > 0
        assert mode != "SHORT_ONLY" or t.side == "short"
        assert mode != "LONG_ONLY" or t.side == "long"
    cls = context["registry"].implementation(exp.strategy.id)
    risk = parameter_risk(cls, context["template"].risk, params)
    assert risk.risk_per_trade_pct == context["template"].risk.risk_per_trade_pct
    assert risk.sizing_method == context["template"].risk.sizing_method


def test_quarter_integrity_warmup_and_market_guards(small):
    root, raw, _ = small
    path, exp = save(root, raw)
    context = prepare(path, exp, full=True)
    assert context["frames"]
    changed = dict(raw)
    changed["markets"] = [raw["markets"][0] | {"warmup_bars": 999}]
    with pytest.raises(ValueError, match="warmup"):
        prepare(path, Experiment.model_validate(changed))
    changed["markets"] = [raw["markets"][0] | {"dataset_id": "f" * 64}]
    with pytest.raises(ValueError, match="identity"):
        prepare(path, Experiment.model_validate(changed))
    changed = raw | {
        "modes": ["LONG_ONLY"],
        "execution": raw["execution"] | {"market_mode": "spot"},
    }
    with pytest.raises(ValueError, match="synthetic"):
        prepare(path, Experiment.model_validate(changed))
    (root / "data/quarters/data.parquet").write_bytes(b"bad")
    with pytest.raises(ValueError, match="SHA256"):
        load_bundle(context["datasets"][0])


def test_small_runs_reports_and_comparison(small):
    root, raw, _ = small
    paths = []
    for name, variant in zip(NAMES, ("V1", "V1", "V2", "V3"), strict=True):
        tiny = raw | {
            "experiment_id": name,
            "strategy_parameters": raw["strategy_parameters"] | {"variant": [variant]},
        }
        path, exp = save(root, tiny)
        assert main(["--root", str(root), "validate", name, "--full"]) == 0
        out = run(path, exp, root)
        paths.append(out)
        assert main(["--root", str(root), "report", name]) == 0
        metrics = pd.read_csv(out / "metrics.csv")
        assert set(metrics.period) == {"train", "validation", "test"}
        assert set(metrics["mode"]) == {"LONG_ONLY", "SHORT_ONLY", "LONG_SHORT"}
        assert {
            "long_trades",
            "short_trades",
            "expectancy",
            "sortino",
            "fees_paid",
            "funding_pnl",
        } <= set(metrics)
        assert metrics.funding_pnl.isna().all()
        assert (out / "ai_summary.md").read_bytes() == (out / "summary.md").read_bytes()
    before = [(p / "ai_summary.md").read_bytes() for p in paths]
    out = compare(root, NAMES)
    comparison = pd.read_csv(out / "comparison.csv")
    assert set(comparison.experiment) == set(NAMES)
    assert comparison.parameter_configurations.eq(1).all()
    assert comparison.configurations_all_markets_modes.eq(3).all()
    assert comparison.valid_configurations.eq(1).all()
    assert len(comparison) == 4 * 3 * 3
    assert (out / "summary.md").read_bytes() == (out / "ai_summary.md").read_bytes()
    assert [(p / "ai_summary.md").read_bytes() for p in paths] == before
    assert main(["--root", str(root), "compare", *NAMES]) == 0
    assert main(["--root", str(root), "strategies"]) == 0
