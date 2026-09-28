import copy
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from quant_lab.config import load_yaml
from quant_lab.history import HistoryRequest
from quant_lab.history_cache import save_bundle
from quant_lab.lab_cli import create, main
from quant_lab.lab_reporting import failure_reasons, locate
from quant_lab.lab_runner import prepare, run
from quant_lab.lab_schema import Experiment, discover, resolve
from quant_lab.strategies.registry import StrategyRegistry


@pytest.fixture
def lab(tmp_path):
    root = tmp_path
    (root / "configs/experiments").mkdir(parents=True)
    source = Path(__file__).resolve().parents[2]
    for name in ("app.yaml", "risk.yaml"):
        shutil.copyfile(source / "configs" / name, root / "configs" / name)
    shutil.copyfile(source / "pyproject.toml", root / "pyproject.toml")
    template = {
        "name": "trend_following",
        "enabled": True,
        "parameters": {"donchian_period": 3, "ema_period": 4},
    }
    (root / "configs/strategy.yaml").write_text(yaml.safe_dump(template), encoding="utf-8")
    history = HistoryRequest(
        start=datetime(2022, 1, 2, tzinfo=UTC),
        end=datetime(2022, 1, 18, tzinfo=UTC),
        warmup_bars=24,
    )
    index = pd.date_range(history.download_start, history.end, freq="h", inclusive="left")
    price = 100 + 0.002 * np.arange(len(index)) + np.sin(np.arange(len(index)) / 8)
    frame = pd.DataFrame(
        {"open": price, "high": price + 0.08, "low": price - 0.08, "close": price, "volume": 10.0},
        index=index,
    )
    bundle = save_bundle(root / "data", frame, history, [])

    def period(day):
        return datetime(2022, 1, day, tzinfo=UTC)

    raw = {
        "experiment_id": "example",
        "created_at": datetime(2026, 9, 27, tzinfo=UTC),
        "description": "Synthetic integration only",
        "app": "../app.yaml",
        "strategy": {"id": "trend_following", "config": "../strategy.yaml"},
        "markets": [
            {
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "dataset": "../../data/" + bundle.name,
                "warmup_bars": 24,
            }
        ],
        "strategy_parameters": {"donchian_period": [3, 6]},
        "execution": {
            "quantity_step": 0.000001,
            "min_quantity": 0.000001,
            "min_notional": 1.0,
            "filter_assumption": "Synthetic fixture",
        },
        "validation": {
            "train": {"start": period(2), "end": period(7)},
            "validation": {"start": period(7), "end": period(12)},
            "test": {"start": period(12), "end": period(17)},
            "walk_forward": [
                {
                    "train": {"start": period(2), "end": period(7)},
                    "test": {"start": period(7), "end": period(12)},
                }
            ],
            "cost_stress": {
                "adverse": {"trading_fee_pct": 0.1, "slippage_pct": 0.06, "spread_pct": 0.02}
            },
        },
        "ranking": {"metric": "return_pct"},
    }
    path = root / "configs/experiments/example.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return root, path, raw, frame


def test_catalogue_and_capabilities():
    registry = StrategyRegistry().discover()
    entries = {r["strategy_id"]: r for r in registry.catalogue()}
    assert entries["trend_following"]["timeframes"] == ("1h", "4h", "1d")
    assert entries["vol_momentum"]["modes"] == ("LONG_ONLY",)
    assert entries["mtf_ema_adx"]["execution"] == "legacy_mtf"
    assert all("created_at" in row and "implementation" in row for row in entries.values())


def test_discovery_latest_and_duplicate(lab):
    _, path, _, _ = lab
    created = create(path.parent, "example", "second")
    assert resolve(path.parent, "latest-experiment")[1].experiment_id == "second"
    assert created.exists()
    with pytest.raises(ValueError, match="Duplicate"):
        create(path.parent, "example", "example")
    shutil.copyfile(path, path.parent / "duplicate.yaml")
    with pytest.raises(ValueError, match="Duplicate experiment_id"):
        discover(path.parent)


@pytest.mark.parametrize(
    "change",
    [
        {"initial_cash": -1.0},
        {"initial_cash": float("nan")},
        {"unknown": True},
        {"modes": ["SHORT_ONLY"]},
        {"strategy_parameters": {"donchian_period": []}},
        {"modes": ["LONG_ONLY", "LONG_ONLY"]},
    ],
)
def test_invalid_schema(lab, change):
    _, _, raw, _ = lab
    with pytest.raises(ValueError):
        Experiment.model_validate(raw | change)


def test_bad_validation_and_duplicate_yaml(lab):
    _, path, raw, _ = lab
    raw["validation"]["test"] = raw["validation"]["train"]
    with pytest.raises(ValueError, match="chronological"):
        Experiment.model_validate(raw)
    path.write_text(path.read_text() + "\nexperiment_id: overwritten\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate YAML"):
        load_yaml(path, Experiment)


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"strategy": {"id": "missing", "config": "../strategy.yaml"}}, "Unknown strategy"),
        ({"strategy_parameters": {"donchian_periodd": [3]}}, "did you mean"),
        ({"strategy_parameters": {"donchian_period": [1]}}, "greater than or equal"),
        ({"strategy_parameters": {"donchian_period": ["3"]}}, "valid integer"),
        ({"strategy_parameters": {"donchian_period": [3, 3]}}, "Duplicate resolved"),
        ({"strategy": {"id": "mtf_ema_adx", "config": "../strategy.yaml"}}, "legacy_mtf"),
    ],
)
def test_invalid_preflight(lab, changes, error):
    _, path, raw, _ = lab
    with pytest.raises(ValueError, match=error):
        prepare(path, Experiment.model_validate(raw | changes))


def test_fast_vs_full_and_corrupt_data(lab, monkeypatch):
    root, path, raw, _ = lab
    exp = Experiment.model_validate(raw)
    context = prepare(path, exp, full=True)
    assert context["backtests"] == 18
    monkeypatch.setattr("quant_lab.lab_runner.load_bundle", lambda _: pytest.fail("FAST read data"))
    assert prepare(path, exp)["frames"] == []
    monkeypatch.undo()
    parquet = next((root / "data").glob("*/candles.parquet"))
    parquet.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="integrity"):
        prepare(path, exp, full=True)


def test_missing_data_and_warmup(lab):
    _, path, raw, _ = lab
    raw["markets"][0]["warmup_bars"] = 500
    with pytest.raises(ValueError, match="warmup"):
        prepare(path, Experiment.model_validate(raw))
    raw["markets"][0]["dataset"] = "absent"
    with pytest.raises(ValueError, match="Missing local dataset"):
        prepare(path, Experiment.model_validate(raw))


def test_synthetic_end_to_end_immutable_and_training_selection(lab):
    root, path, raw, _ = lab
    exp = Experiment.model_validate(raw)
    first = run(path, exp, root)
    before = hashlib.sha256((first / "ai_summary.md").read_bytes()).hexdigest()
    second = run(path, exp, root)
    assert first != second
    assert hashlib.sha256((first / "ai_summary.md").read_bytes()).hexdigest() == before
    assert locate(root, "latest")["path"] == str(second.resolve())
    metrics = pd.read_csv(first / "metrics.csv")
    assert len(metrics) == 18
    training = metrics[(metrics.period == "wf_0_train") & (metrics.scenario == "base")]
    chosen = training.sort_values(["return_pct", "configuration_id"], ascending=[False, True]).iloc[
        0
    ]
    oos = metrics[metrics.period == "wf_0_test"]
    assert set(oos.configuration_id) == {chosen.configuration_id}
    assert (first / "experiment_snapshot.yaml").read_bytes() == path.read_bytes()
    assert (first / "resolved.json").exists()
    summary = (first / "ai_summary.md").read_text(encoding="utf-8")
    for text in ("Code hash", "Datasets", "Walk-forward", "Parameter patterns", "TRAIN"):
        assert text in summary
    leaderboard = pd.read_csv(first / "leaderboard.csv")
    assert len(leaderboard) == 2
    assert "test_return_pct" in leaderboard
    assert json.loads((first / "outcome.json").read_text())["status"] == "COMPLETE"
    for record in first.glob("*/result.json"):
        document = json.loads(record.read_text())
        for trade in document["trades"]:
            assert pd.Timestamp(trade["entry_time"]) >= pd.Timestamp(document["metrics"]["start"])
            assert pd.Timestamp(trade["signal_close"]) <= pd.Timestamp(trade["entry_time"])


def test_holdout_does_not_change_fold_selection(lab):
    root, path, raw, frame = lab
    first = run(path, Experiment.model_validate(raw), root)
    # Future final holdout cannot change fold's training-selected parameter identity.
    future = frame.index >= raw["validation"]["test"]["start"]
    changed = frame.copy()
    changed.loc[future, ["open", "high", "low", "close"]] *= 1.5
    request = HistoryRequest(
        start=datetime(2022, 1, 2, tzinfo=UTC),
        end=datetime(2022, 1, 18, tzinfo=UTC),
        warmup_bars=24,
    )
    bundle = save_bundle(root / "data", changed, request, [])
    raw["markets"][0]["dataset"] = "../../data/" + bundle.name
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    second = run(path, Experiment.model_validate(raw), root)
    a, b = (pd.read_csv(p / "metrics.csv") for p in (first, second))
    columns = ["configuration_id", "return_pct"]
    pd.testing.assert_frame_equal(
        a.loc[a.period == "wf_0_test", columns], b.loc[b.period == "wf_0_test", columns]
    )


def test_failure_lifecycle(lab, monkeypatch):
    root, path, raw, _ = lab

    def fail(*args):
        raise RuntimeError("fixture failure")

    monkeypatch.setattr("quant_lab.lab_runner.evaluate", fail)
    with pytest.raises(RuntimeError, match="fixture failure"):
        run(path, Experiment.model_validate(raw), root)
    assert locate(root, "latest")["status"] == "FAILED"


def test_deterministic_filters(lab):
    _, _, raw, _ = lab
    raw["filters"] = {"minimum_profit_factor": 1.1, "positive_test": True}
    reasons = failure_reasons(
        {
            "status": "completed",
            "period": "test",
            "scenario": "base",
            "closed_trades": 5,
            "max_drawdown_pct": 1.0,
            "profit_factor": None,
            "return_pct": -1,
        },
        Experiment.model_validate(raw),
    )
    assert "profit_factor:min=1.1" in reasons
    assert "nonpositive_test_return" in reasons


def test_cli_smokes(lab, capsys):
    root, _, _, _ = lab
    for command in (
        ["strategies"],
        ["experiments"],
        ["status"],
        ["validate", "latest-experiment"],
        ["validate", "example", "--full"],
    ):
        assert main(["--root", str(root), *command]) == 0
        assert json.loads(capsys.readouterr().out)
    with pytest.raises(SystemExit) as error:
        main(["--root", str(root), "report", "latest"])
    assert error.value.code == 2


def test_four_hour_existing_backend(lab):
    from quant_lab.study_data import audit

    _, path, raw, frame = lab
    four = frame.resample("4h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    quality = audit(four, "BTCUSDT", "4h")
    folder = path.parents[2] / "data" / quality["hash"]
    folder.mkdir()
    four.to_parquet(folder / "candles.parquet")
    manifest = {
        "audit": quality,
        "parquet_sha256": hashlib.sha256((folder / "candles.parquet").read_bytes()).hexdigest(),
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    raw = copy.deepcopy(raw)
    raw["markets"][0].update(timeframe="4h", warmup_bars=6, dataset="../../data/" + folder.name)
    raw["modes"] = ["SHORT_ONLY", "LONG_SHORT"]
    raw["execution"]["market_mode"] = "synthetic"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    result = run(path, Experiment.model_validate(raw), path.parents[2])
    metrics = pd.read_csv(result / "metrics.csv")
    assert set(metrics.direction) == {"short", "combined"}
    assert len(metrics) == 36
