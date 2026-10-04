"""Tiny synthetic lab runs and publication; never execute the 144-point grid."""

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from quant_lab.config import load_yaml
from quant_lab.features import atr
from quant_lab.lab_classification import classify
from quant_lab.lab_cli import main
from quant_lab.lab_comparison import compare
from quant_lab.lab_publish import publish, publish_comparison
from quant_lab.lab_runner import evaluate, parameter_risk, prepare, run
from quant_lab.lab_schema import Experiment
from quant_lab.study_data import audit

ROOT = Path(__file__).resolve().parents[2]
NAMES = ["trend_volatility_breakout_v1_" + a + "_1h" for a in ("eth", "btc")]
POLICY = ROOT / "configs/research/lab_classification_v1.yaml"
GRID = {
    "trend_length": [100, 200],
    "breakout_length": [20, 50],
    "atr_length": [14, 20],
    "atr_expansion_threshold": [1.0, 1.25],
    "atr_stop_multiplier": [1.5, 2.0, 2.5],
    "reward_risk": [1.5, 2.0, 2.5],
    "slope_lookback": [5],
}


def test_frozen_grid_markets_periods_costs_and_risk():
    reference = load_yaml(
        ROOT / "configs/experiments/trend_rsi_pullback_v1_single_tf.yaml", Experiment
    )
    for name, asset in zip(NAMES, ("ETHUSDT", "BTCUSDT"), strict=True):
        exp = load_yaml(ROOT / "configs/experiments" / (name + ".yaml"), Experiment)
        assert exp.strategy_parameters == GRID
        assert len(list(exp.grid())) == exp.combinations == 144
        assert len(exp.markets) == 1 and exp.markets[0].symbol == asset
        assert exp.markets[0].timeframe == "1h" and exp.markets[0].warmup_bars == 1000
        assert exp.validation == reference.validation and len(exp.validation.walk_forward) == 4
        assert exp.modes == ["LONG_ONLY", "SHORT_ONLY", "LONG_SHORT"]
        assert exp.costs is None  # BASE inherits centralized app.yaml.
        assert exp.validation.cost_stress == reference.validation.cost_stress
        profile = yaml.safe_load(
            (ROOT / "configs/strategies/trend_volatility_breakout_v1.yaml").read_text()
        )
        assert profile["parameters"]["atr_reference_length"] == 50
        assert profile["risk"] == {
            "stop_method": "atr",
            "stop_enabled": True,
            "take_profit_enabled": True,
            "trailing_atr_multiplier": None,
            "max_holding_bars": None,
        }


@pytest.fixture
def small(tmp_path):
    (tmp_path / "configs/experiments").mkdir(parents=True)
    (tmp_path / "configs/strategies").mkdir()
    for file in ("app.yaml", "risk.yaml", "strategies/trend_volatility_breakout_v1.yaml"):
        shutil.copyfile(ROOT / "configs" / file, tmp_path / "configs" / file)
    shutil.copyfile(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    n = 400
    x = np.arange(n)
    price = 200 + 10 * np.sin(x / 12) + 0.01 * x
    frame = pd.DataFrame(
        {"open": price, "high": price + 0.1, "low": price - 0.1, "close": price, "volume": 10.0},
        index=pd.date_range("2022-01-01", periods=n, freq="h", tz="UTC"),
    )
    raw = yaml.safe_load((ROOT / "configs/experiments" / (NAMES[0] + ".yaml")).read_text())
    points = [frame.index[i].to_pydatetime() for i in (100, 200, 300)] + [
        (frame.index[-1] + pd.Timedelta(hours=1)).to_pydatetime()
    ]
    raw["strategy_parameters"] = {
        "trend_length": [10],
        "slope_lookback": [2],
        "breakout_length": [3],
        "atr_length": [2],
        "atr_expansion_threshold": [1.0],
        "atr_stop_multiplier": [2.5],
        "reward_risk": [1.5],
    }
    raw["validation"] = {
        label: {"start": points[i], "end": points[i + 1]}
        for i, label in enumerate(("train", "validation", "test"))
    } | {
        "walk_forward": [
            {
                "train": {"start": points[0], "end": points[1]},
                "test": {"start": points[1], "end": points[2]},
            }
        ],
        "cost_stress": raw["validation"]["cost_stress"],
    }
    return tmp_path, raw, frame


def save(root, raw, frame, asset="ETHUSDT"):
    quality = audit(frame, asset, "1h")
    directory = root / "data" / quality["hash"]
    directory.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(directory / "candles.parquet")
    manifest = {
        "audit": quality,
        "parquet_sha256": hashlib.sha256((directory / "candles.parquet").read_bytes()).hexdigest(),
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    raw = raw | {
        "markets": [
            {
                "symbol": asset,
                "timeframe": "1h",
                "warmup_bars": 65,
                "dataset": "../../data/" + directory.name,
                "dataset_id": directory.name,
            }
        ]
    }
    path = root / "configs/experiments" / (raw["experiment_id"] + ".yaml")
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path, Experiment.model_validate(raw)


@pytest.mark.parametrize("mode", ["LONG_ONLY", "SHORT_ONLY", "LONG_SHORT"])
def test_real_strategy_next_open_signal_atr_stops_rr_and_modes(small, mode):
    root, raw, frame = small
    path, exp = save(root, raw, frame)
    context = prepare(path, exp, full=True)
    context["execution"] = exp.execution
    params = context["parameters"][0]
    result = evaluate(
        context, frame, exp.markets[0], mode, params, exp.validation.train, context["app"].costs
    )
    assert result.trades
    distances = atr(frame, 2) * 2.5
    strategy = context["registry"].create(
        context["template"].model_copy(update={"parameters": params})
    )
    signals = strategy.generate_signals(frame)
    for t in result.trades:
        previous = t.entry_time - pd.Timedelta(hours=1)
        index = frame.index.get_loc(previous)
        assert (signals.long_entries if t.side == "long" else signals.short_entries)[index]
        assert t.signal_close == previous + pd.Timedelta(hours=1) == t.entry_time
        assert t.entry_time > previous
        assert t.entry_reference == frame.loc[t.entry_time, "open"]
        side = 1 if t.side == "long" else -1
        assert t.stop == pytest.approx(t.entry_price - side * distances.loc[previous])
        assert t.target == pytest.approx(t.entry_price + side * distances.loc[previous] * 1.5)
        assert t.entry_fee > 0 and t.exit_fee > 0
    sides = {t.side for t in result.trades}
    assert sides == (
        {"long", "short"} if mode == "LONG_SHORT" else {"long" if mode == "LONG_ONLY" else "short"}
    )
    cls = context["registry"].implementation(exp.strategy.id)
    risk = parameter_risk(cls, context["template"].risk, params)
    assert risk.atr_period == 2 and risk.atr_multiplier == 2.5 and risk.risk_reward == 1.5
    for field in ("risk_per_trade_pct", "sizing_method", "max_position_pct", "max_exposure_pct"):
        assert getattr(risk, field) == getattr(context["template"].risk, field)


def test_gap_in_period_or_warmup_rejected(small):
    root, raw, frame = small
    for index in (80, 150):
        path, exp = save(root, raw, frame.drop(frame.index[index]))
        with pytest.raises(ValueError, match="gap"):
            prepare(path, exp)


def test_warmup_signals_cannot_open_scored_positions(small):
    from quant_lab.lab_runner import window
    from quant_lab.strategies.base import Signals
    from quant_lab.study_backend import StudyBackend

    root, raw, frame = small
    path, exp = save(root, raw, frame)
    context = prepare(path, exp)
    view, segment = window(frame, exp.markets[0], exp.validation.train)
    # An entry on every context close, including the last one before scoring.
    warmup_only = tuple(t < segment.start for t in view.index)
    false = (False,) * len(view)
    signals = Signals(warmup_only, false, false, false)
    result = StudyBackend().run(
        view,
        signals,
        pd.Series(1.0, index=view.index),
        segment,
        context["app"],
        context["template"].risk,
        exp.execution,
    )
    assert not result.trades and result.open_position is None


@pytest.mark.parametrize("mode", ["LONG_ONLY", "SHORT_ONLY"])
def test_price_gap_entry_uses_known_atr_and_stop_gap_fills_at_open(small, mode):
    root, raw, frame = small
    path, exp = save(root, raw, frame)
    context = prepare(path, exp)
    context["execution"] = exp.execution
    params = context["parameters"][0]

    def evaluate_frame(data):
        return evaluate(
            context, data, exp.markets[0], mode, params, exp.validation.train, context["app"].costs
        )

    first = evaluate_frame(frame).trades[0]
    changed = frame.copy()
    # Change entry OHLC only: the signal and ATR on the previous close are frozen.
    side = 1 if mode == "LONG_ONLY" else -1
    changed.loc[first.entry_time, ["open", "high", "low", "close"]] += side * 0.5
    newer = evaluate_frame(changed).trades[0]
    assert newer.entry_time == first.entry_time
    assert newer.entry_reference == pytest.approx(first.entry_reference + side * 0.5)
    assert abs(newer.entry_price - newer.stop) == pytest.approx(abs(first.entry_price - first.stop))
    gap_time = newer.entry_time + pd.Timedelta(hours=1)
    gap_open = newer.stop - side * 2
    changed.loc[gap_time, ["open", "high", "low", "close"]] = [
        gap_open,
        gap_open + 0.1,
        gap_open - 0.1,
        gap_open,
    ]
    stopped = evaluate_frame(changed).trades[0]
    assert stopped.reason == "stop_gap"
    assert stopped.exit_time == gap_time
    assert stopped.exit_reference == gap_open


def test_tiny_runs_classify_compare_publish_and_immutable_results(small, monkeypatch):
    root, raw, frame = small
    outputs = []
    for name, asset in zip(NAMES, ("ETHUSDT", "BTCUSDT"), strict=True):
        path, exp = save(root, raw | {"experiment_id": name}, frame, asset)
        assert main(["--root", str(root), "validate", name, "--full"]) == 0
        context = prepare(path, exp)
        assert len(context["parameters"]) == 1 and context["backtests"] == 30
        out = run(path, exp, root)
        outputs.append(out)
        metrics = pd.read_csv(out / "metrics.csv")
        assert metrics.funding_pnl.isna().all()
        assert set(metrics.symbol) == {asset}
        assert metrics.closed_trades.sum() > 0
    before = [(p / "metrics.csv").read_bytes() for p in outputs]
    monkeypatch.setattr("quant_lab.lab_runner.evaluate", lambda *args: pytest.fail("No rerun"))
    for name in NAMES:
        directory = classify(root, name, POLICY)
        document = json.loads((directory / "classification.json").read_text())
        assert len(document["candidates"]) == 3
        assert main(["--root", str(root), "report", name]) == 0
        publication = publish(root, name)
        destination = Path(publication["publication_directory"])
        assert destination.is_relative_to(root / "research_results/trend_volatility_breakout")
        assert {
            "classification.json",
            "classification.md",
            "metrics_compact.csv",
            "metadata.json",
            "ai_summary.md",
            "summary.md",
        } <= set(publication["published"])
        assert not list(destination.rglob("*.parquet"))
    comparison = compare(root, NAMES)
    table = pd.read_csv(comparison / "comparison.csv")
    assert set(table.experiment) == set(NAMES)
    publication = publish_comparison(root, comparison.name)
    assert "comparison.csv" in publication["published"]
    assert [(p / "metrics.csv").read_bytes() for p in outputs] == before


def test_offline_price_preparation_preserves_bars_checks_identity_and_hashes(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "price_prepare", ROOT / "scripts/prepare_lab_1h_prices.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    frame = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 10.0},
        index=pd.date_range("2022-01-01", periods=100, freq="h", tz="UTC"),
    )
    body = frame.to_json(date_format="iso", double_precision=15).encode()
    identity = hashlib.sha256(b"USD_M_PERPETUAL/ETHUSDT/klines/1h" + body).hexdigest()
    monkeypatch.setitem(module.SOURCES, "ETHUSDT", identity)
    source = tmp_path / "data/batch_006_perpetual/ETHUSDT/klines/1h" / identity
    source.mkdir(parents=True)
    frame.to_parquet(source / "data.parquet")
    manifest = {
        "exchange": "binance",
        "market_type": "USD_M_PERPETUAL",
        "asset": "ETHUSDT",
        "kind": "klines",
        "timeframe": "1h",
        "hash": identity,
        "start": str(frame.index[0]),
        "end": str(frame.index[-1]),
        "rows": len(frame),
        "parquet_sha256": hashlib.sha256((source / "data.parquet").read_bytes()).hexdigest(),
    }
    (source / "manifest.json").write_text(json.dumps(manifest))
    out = module.prepare(tmp_path, "ETHUSDT")
    pd.testing.assert_frame_equal(pd.read_parquet(out / "candles.parquet"), frame, check_freq=False)
    assert module.prepare(tmp_path, "ETHUSDT") == out
    (out / "candles.parquet").write_bytes(b"bad")
    with pytest.raises(ValueError, match="SHA256"):
        module.prepare(tmp_path, "ETHUSDT")
    (source / "data.parquet").write_bytes(b"bad")
    with pytest.raises(ValueError, match="SHA256"):
        module.prepare(tmp_path, "ETHUSDT")
    manifest["asset"] = "BTCUSDT"
    (source / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="identity"):
        module.prepare(tmp_path, "ETHUSDT")


@pytest.mark.parametrize("frequency,with_gap", [("h", False), ("h", True), ("15min", False)])
def test_native_hourly_source_rejects_disguised_quarters_and_keeps_real_gaps(
    tmp_path, monkeypatch, frequency, with_gap
):
    spec = importlib.util.spec_from_file_location(
        "price_prepare", ROOT / "scripts/prepare_lab_1h_prices.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    frame = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 10.0},
        index=pd.date_range("2022-01-01", periods=100, freq=frequency, tz="UTC"),
    )
    if with_gap:
        frame = frame.drop(frame.index[50])
    body = frame.to_json(date_format="iso", double_precision=15).encode()
    identity = hashlib.sha256(b"USD_M_PERPETUAL/ETHUSDT/klines/1h" + body).hexdigest()
    monkeypatch.setitem(module.SOURCES, "ETHUSDT", identity)
    source = tmp_path / "data/batch_006_perpetual/ETHUSDT/klines/1h" / identity
    source.mkdir(parents=True)
    frame.to_parquet(source / "data.parquet")
    before = (source / "data.parquet").read_bytes()
    manifest = {
        "exchange": "binance",
        "market_type": "USD_M_PERPETUAL",
        "asset": "ETHUSDT",
        "kind": "klines",
        "timeframe": "1h",
        "hash": identity,
        "start": str(frame.index[0]),
        "end": str(frame.index[-1]),
        "rows": len(frame),
        "parquet_sha256": hashlib.sha256(before).hexdigest(),
    }
    (source / "manifest.json").write_text(json.dumps(manifest))
    if frequency == "15min":
        with pytest.raises(ValueError, match="Native 1h"):
            module.prepare(tmp_path, "ETHUSDT")
        assert not (tmp_path / "data/lab_1h_prices").exists()
    else:
        out = module.prepare(tmp_path, "ETHUSDT")
        pd.testing.assert_frame_equal(
            pd.read_parquet(out / "candles.parquet"), frame, check_freq=False
        )
        assert json.loads((out / "manifest.json").read_text())["audit"]["missing_bars"] == int(
            with_gap
        )
    assert (source / "data.parquet").read_bytes() == before
