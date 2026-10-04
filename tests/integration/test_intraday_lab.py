"""Small fixtures for structural protection, annual diagnostics and lab publication."""

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from quant_lab.config import AppConfig, CostsConfig, RiskConfig, load_yaml
from quant_lab.execution_config import ExecutionConfig
from quant_lab.intraday_metrics import diagnostic_result
from quant_lab.lab_cli import main
from quant_lab.lab_comparison import compare
from quant_lab.lab_evidence import completed_run
from quant_lab.lab_publish import publish, publish_comparison
from quant_lab.lab_runner import prepare, run
from quant_lab.lab_schema import Experiment
from quant_lab.mtf_data import quarter_audit
from quant_lab.strategies.base import Signals
from quant_lab.study_backend import Segment, StudyBackend

ROOT = Path(__file__).resolve().parents[2]
NAMES = ("volatility_breakout_intraday_v1", "range_mean_reversion_v1")


def structural(side=1, *, opening=None, both_levels=False, direction="combined", levels=None):
    entry = 94.0 if side == 1 else 106.0
    frame = pd.DataFrame(
        [
            [entry, entry + 1, entry - 1, entry],
            [entry, entry + 1, entry - 1, entry],
            [entry, 101.0 if side == 1 else 107.0, 93.0 if side == 1 else 99.0, 100.0],
        ],
        columns=["open", "high", "low", "close"],
        index=pd.date_range("2022-01-01", periods=3, freq="15min", tz="UTC"),
    )
    if opening is not None:
        frame.iloc[1] = [opening, opening + 1, opening - 1, opening]
    if both_levels:
        frame.iloc[1] = [entry, 111.0, 89.0, entry]
    frame["volume"] = 10.0
    signal = Signals(
        (side == 1, False, False), (False,) * 3, (side == -1, False, False), (False,) * 3
    )
    anchors = (
        pd.DataFrame(
            {"long_stop": 90.0, "long_target": 100.0, "short_stop": 110.0, "short_target": 100.0},
            index=frame.index,
        )
        if levels is None
        else levels(frame)
    )
    risk = RiskConfig(stop_method="structure")
    app = AppConfig(costs=CostsConfig())
    result = StudyBackend().run(
        frame,
        signal,
        pd.Series(2.0, index=frame.index),
        Segment("BTCUSDT", "15m", frame.index[0], frame.index[-1] + pd.Timedelta(minutes=15)),
        app,
        risk,
        ExecutionConfig(
            market_mode="synthetic",
            direction=direction,
            quantity_step=0.000001,
            min_quantity=0.000001,
            min_notional=10.0,
            filter_assumption="Fixed filters for synthetic execution tests",
        ),
        entry_levels=anchors,
    )
    return result, frame, signal


@pytest.mark.parametrize("side", [1, -1])
def test_absolute_midpoint_next_open_cost_sizing_and_frozen_levels(side):
    result, frame, signal = structural(side)
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_time == frame.index[1] and trade.signal_close == frame.index[1]
    assert trade.entry_reference == frame.open.iloc[1]
    assert trade.target == 100.0 and trade.stop == (90.0 if side == 1 else 110.0)
    assert trade.reason == "target" and trade.exit_time is None
    assert trade.entry_fee > 0 and trade.exit_fee > 0
    assert trade.expected_stop_loss <= trade.risk_budget
    extras = diagnostic_result(
        result,
        frame,
        signal,
        Segment("BTCUSDT", "15m", frame.index[0], frame.index[-1] + pd.Timedelta(minutes=15)),
        "range_mean_reversion_v1",
    ).diagnostics
    assert extras["midpoint_exit_pct"] == 100.0
    assert extras["gross_price_pnl"] - extras["total_modeled_costs"] == pytest.approx(trade.net_pnl)
    assert extras["total_modeled_costs"] == pytest.approx(
        trade.entry_fee + trade.exit_fee + trade.slippage_cost + trade.spread_cost
    )

    def future_levels(frame):
        f = pd.DataFrame(
            {"long_stop": 90.0, "long_target": 100.0, "short_stop": 110.0, "short_target": 100.0},
            index=frame.index,
        )
        f.iloc[1:] = [80.0, 150.0, 120.0, 50.0]
        return f

    frozen, _, _ = structural(side, levels=future_levels)
    assert frozen.trades == result.trades


@pytest.mark.parametrize("side", [1, -1])
def test_structural_stop_first_when_both_protections_touched(side):
    result, _, _ = structural(side, both_levels=True)
    assert len(result.trades) == 1 and result.trades[0].reason == "stop"


@pytest.mark.parametrize("side,opening", [(1, 89.0), (1, 101.0), (-1, 111.0), (-1, 99.0)])
def test_next_open_outside_frozen_range_rejected(side, opening):
    result, _, _ = structural(side, opening=opening)
    assert not result.trades
    assert result.rejections[0].reason == "open_outside_frozen_levels"


@pytest.mark.parametrize("side,direction", [(1, "short"), (-1, "long")])
def test_side_mode_cannot_execute_opposite_signal(side, direction):
    result, _, _ = structural(side, direction=direction)
    assert not result.trades


@pytest.fixture
def lab(tmp_path):
    (tmp_path / "configs/experiments").mkdir(parents=True)
    (tmp_path / "configs/strategies").mkdir()
    for file in ("app.yaml", "risk.yaml"):
        shutil.copyfile(ROOT / "configs" / file, tmp_path / "configs" / file)
    shutil.copyfile(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    price = 100 + 2 * np.sin(np.arange(300) / 7)
    opened = np.r_[price[0], price[:-1]]
    frame = pd.DataFrame(
        {
            "open": opened,
            "high": np.maximum(price, opened) + 0.05,
            "low": np.minimum(price, opened) - 0.05,
            "close": price,
            "volume": 10.0,
        },
        index=pd.date_range("2022-01-01", periods=300, freq="15min", tz="UTC"),
    )
    bundle = tmp_path / "data/quarters"
    bundle.mkdir(parents=True)
    frame.to_parquet(bundle / "data.parquet")
    manifest = {
        "audit": quarter_audit(frame, "BTCUSDT"),
        "sha256": hashlib.sha256((bundle / "data.parquet").read_bytes()).hexdigest(),
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path, frame, manifest


def tiny(lab, name):
    root, frame, manifest = lab
    shutil.copyfile(
        ROOT / "configs/strategies" / f"{name}.yaml", root / "configs/strategies" / f"{name}.yaml"
    )
    raw = yaml.safe_load((ROOT / "configs/experiments" / f"{name}_btc_eth_15m.yaml").read_text())
    raw["markets"] = [
        raw["markets"][0]
        | {
            "dataset": "../../data/quarters",
            "dataset_id": manifest["audit"]["hash"],
            "warmup_bars": 84,
        }
    ]
    params = {"ema_period": [2], "ema_slope_lookback": [1], "atr_period": [3]}
    params |= (
        {
            "compression_window": [10],
            "breakout_lookback": [5],
            "atr_reference_window": [3],
            "compression_ratio": [1.0],
            "atr_expansion_factor": [1.0],
            "momentum_threshold": [0.01],
        }
        if name == NAMES[0]
        else {
            "adx_period": [2],
            "adx_threshold": [100.0],
            "max_ema_slope_pct": [100.0],
            "range_lookback": [8],
            "minimum_range_atr": [0.5],
        }
    )
    raw["strategy_parameters"] = params
    points = [frame.index[i].to_pydatetime() for i in (120, 160, 200, 240)]
    raw["validation"] |= {
        label: {"start": points[i], "end": points[i + 1]}
        for i, label in enumerate(("train", "validation", "test"))
    }
    raw["diagnostic_periods"] = {
        "diagnostic_first": {"start": points[0], "end": points[1]},
        "diagnostic_second": {"start": points[1], "end": points[-1]},
    }
    path = root / "configs/experiments" / f"{raw['experiment_id']}.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return path, Experiment.model_validate(raw)


def test_frozen_real_configs_one_candidate_no_wf_selection():
    for name in NAMES:
        path = ROOT / "configs/experiments" / f"{name}_btc_eth_15m.yaml"
        exp = load_yaml(path, Experiment)
        context = prepare(path, exp)
        assert exp.combinations == len(context["parameters"]) == 1
        assert context["backtests"] == 120
        assert not exp.validation.walk_forward
        assert set(exp.diagnostic_periods) == {f"diagnostic_{y}" for y in range(2020, 2027)}
        assert exp.markets[0].warmup_bars == exp.markets[1].warmup_bars == 2004
        assert context["app"].costs == CostsConfig()
        assert context["scenarios"]["adverse"] == CostsConfig(
            trading_fee_pct=0.1, slippage_pct=0.06, spread_pct=0.02
        )


def test_real_lab_run_resume_compare_compact_publication_and_metrics(lab):
    root, _, _ = lab
    source_hashes = []
    experiments = []
    for name in NAMES:
        path, exp = tiny(lab, name)
        experiments.append(exp.experiment_id)
        assert main(["--root", str(root), "validate", exp.experiment_id, "--full"]) == 0
        source = run(path, exp, root)
        evidence = completed_run(root, source.name)
        table = evidence["metrics"]
        assert len(table) == 30
        assert table.status.eq("completed").all()
        assert set(table.period) == {
            "train",
            "validation",
            "test",
            "diagnostic_first",
            "diagnostic_second",
        }
        assert table.closed_trades.sum() > 0
        assert {"gross_return_pct", "total_modeled_costs", "average_holding_hours"} <= set(table)
        for mode, group in table.groupby("mode"):
            if mode == "LONG_ONLY":
                assert group.short_trades.eq(0).all()
            if mode == "SHORT_ONLY":
                assert group.long_trades.eq(0).all()
        before = (source / "metrics.csv").read_bytes()
        source_hashes.append((source, before))
        audit = run(path, exp, root, resume=source.name, check_only=True)
        assert audit["verified_reusable"] == 30 and audit["pending_backtests"] == 0
        assert run(path, exp, root, resume=source.name) == source
        publication = publish(root, exp.experiment_id)
        compact = pd.read_csv(Path(publication["publication_directory"]) / "metrics_compact.csv")
        assert len(compact) == 30 and "total_modeled_costs" in compact
        assert not list(Path(publication["publication_directory"]).rglob("*.parquet"))
    comparison = compare(root, experiments)
    table = pd.read_csv(comparison / "comparison.csv")
    assert table.symbol.eq("BTCUSDT").all() and len(table) == 60
    assert "comparison.csv" in publish_comparison(root, comparison.name)["published"]
    assert all((source / "metrics.csv").read_bytes() == before for source, before in source_hashes)


@pytest.mark.parametrize("fault", ["label", "outside", "overlap"])
def test_diagnostic_schema_rejects_ambiguous_periods(lab, fault):
    path, exp = tiny(lab, NAMES[0])
    raw = yaml.safe_load(path.read_text())
    if fault == "label":
        raw["diagnostic_periods"] = {"train": raw["diagnostic_periods"]["diagnostic_first"]}
    elif fault == "outside":
        raw["diagnostic_periods"]["diagnostic_first"]["start"] -= pd.Timedelta(days=1)
    else:
        raw["diagnostic_periods"]["diagnostic_second"]["start"] = exp.validation.train.start
    with pytest.raises(ValueError):
        Experiment.model_validate(raw)
