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
from quant_lab.lab_rmm_falsification import FOLDER, LOCK, VARIANTS, report
from quant_lab.lab_runner import evaluate, prepare, run
from quant_lab.lab_schema import Experiment
from quant_lab.study_data import audit

ROOT = Path(__file__).resolve().parents[2]


def small_protocol(root):
    shutil.copytree(ROOT / "configs", root / "configs")
    shutil.copytree(ROOT / "src", root / "src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(ROOT / "pyproject.toml", root / "pyproject.toml")
    spec = yaml.safe_load((ROOT / FOLDER / "frozen_candidates.yaml").read_text())
    idx = pd.date_range("2020-01-01", periods=1400, freq="4h", tz="UTC")
    prices = 100 * np.exp(0.1 * np.sin(np.arange(1400) / 30) + 0.0001 * np.arange(1400))
    candles = pd.DataFrame(
        dict(open=prices, high=prices + 1, low=prices - 1, close=prices, volume=1.0), index=idx
    )
    markets = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        quality = audit(candles, symbol, "4h")
        target = root / "data" / quality["hash"]
        target.mkdir(parents=True)
        candles.to_parquet(target / "candles.parquet")
        (target / "manifest.json").write_text(
            json.dumps(
                dict(
                    audit=quality,
                    parquet_sha256=hashlib.sha256(
                        (target / "candles.parquet").read_bytes()
                    ).hexdigest(),
                )
            )
        )
        markets.append(
            dict(
                symbol=symbol,
                timeframe="4h",
                dataset=str(target),
                dataset_id=quality["hash"],
                warmup_bars=1000,
            )
        )

    def period(a, b):
        return dict(start=idx[a].to_pydatetime(), end=idx[b].to_pydatetime())

    for variant, plan in spec["experiments"].items():
        plan = Experiment.model_validate_json(json.dumps(plan)).model_dump()
        plan["markets"] = markets
        plan["validation"] |= dict(
            train=period(1000, 1080),
            validation=period(1080, 1160),
            test=period(1160, 1320),
            walk_forward=[dict(train=period(1000, 1040), test=period(1040, 1080))],
        )
        plan["diagnostic_periods"] = dict(diagnostic_small=period(1000, 1320))
        exp = Experiment.model_validate(plan)
        path = root / "configs/experiments" / (exp.experiment_id + ".yaml")
        path.write_text(yaml.safe_dump(exp.model_dump(), sort_keys=False))
        spec["experiments"][variant] = exp.model_dump(mode="json")
    spec["file_sha256"] = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in spec["file_sha256"]
    }
    target = root / FOLDER
    target.mkdir(parents=True)
    (target / "frozen_candidates.yaml").write_text(yaml.safe_dump(spec, sort_keys=False))
    (root / LOCK).write_text(
        yaml.safe_dump(
            dict(
                frozen_sha256=hashlib.sha256(
                    (target / "frozen_candidates.yaml").read_bytes()
                ).hexdigest()
            )
        )
    )
    return spec


def test_real_lab_wf_fixed_control_reporting_provenance_and_corruption(tmp_path, capsys):
    spec = small_protocol(tmp_path)
    runs = []
    before = {}
    for variant in VARIANTS:
        path = (
            tmp_path
            / "configs/experiments"
            / (spec["experiments"][variant]["experiment_id"] + ".yaml")
        )
        exp = load_yaml(path, Experiment)
        context = prepare(path, exp, full=True)
        assert context["backtests"] == 48
        context["execution"] = exp.execution
        if variant in {"scaled_180", "fixed_180"}:
            result = evaluate(
                context,
                context["frames"][0],
                exp.markets[0],
                "LONG_SHORT",
                context["parameters"][0],
                exp.validation.test,
                context["app"].costs,
            )
            if variant == "scaled_180":
                original = result
                original_strategy = context["registry"].create(context["template"])
            else:
                control_strategy = context["registry"].create(context["template"])
                assert original_strategy.generate_signals(
                    context["frames"][0]
                ) == control_strategy.generate_signals(context["frames"][0])
                assert len(result.trades) == len(original.trades) > 0
                assert [(t.entry_time, t.exit_bar_open, t.side) for t in original.trades] == [
                    (t.entry_time, t.exit_bar_open, t.side) for t in result.trades
                ]
                assert any(
                    a.quantity != b.quantity
                    for a, b in zip(original.trades, result.trades, strict=True)
                )
        source = run(path, exp, tmp_path)
        runs.append(source)
        before[source] = (source / "metrics.csv").read_bytes()
        metrics = pd.read_csv(source / "metrics.csv")
        assert len(metrics[metrics.period == "wf_0_test"]) == 8
        assert set(metrics["mode"]) == {"LONG_ONLY", "LONG_SHORT"}
    assert (
        main(
            ["--root", str(tmp_path), "falsification", "report", "--runs", *[p.name for p in runs]]
        )
        == 0
    )
    assert "publication_directory" in capsys.readouterr().out
    publications = list((tmp_path / FOLDER).glob("*/outcome.json"))
    assert len(publications) == 1
    output = publications[0].parent
    assert json.loads(publications[0].read_text())["status"] == "COMPLETE"
    table = pd.read_csv(output / "compact_metrics.csv")
    assert len(table) == 192 and set(table.candidate) == {"A", "B", "C", "D"}
    paired = pd.read_csv(output / "sizing_ablation.csv")
    assert len(paired) == 48 and paired.trade_timing_identical.all()
    assert set(pd.read_csv(output / "parameter_robustness.csv").lookback) == {150, 180, 210}
    assert len(pd.read_csv(output / "walk_forward_summary.csv")) == 32
    assert set(pd.read_csv(output / "mfe_mae.csv").side) == {"long", "short"}
    conclusions = json.loads((output / "conclusion.json").read_text())["candidates"]
    assert all(
        v["classification"] == "INCONCLUSIVE" and not v["demo_approved"]
        for v in conclusions.values()
    )
    for source in runs:
        assert (source / "metrics.csv").read_bytes() == before[source]
    freeze_path = tmp_path / FOLDER / "frozen_candidates.yaml"
    lock_path = tmp_path / LOCK
    frozen_before, locked_before = freeze_path.read_bytes(), lock_path.read_bytes()
    freeze_path.write_bytes(frozen_before + b"\n# changed criteria document\n")
    with pytest.raises(ValueError, match="candidates/criteria changed"):
        report(tmp_path, [p.name for p in runs])
    changed = yaml.safe_load(frozen_before)
    changed["guidelines"]["minimum_temporal_trades"] = 1
    freeze_path.write_text(yaml.safe_dump(changed, sort_keys=False))
    lock_path.write_text(
        yaml.safe_dump(dict(frozen_sha256=hashlib.sha256(freeze_path.read_bytes()).hexdigest()))
    )
    with pytest.raises(ValueError, match="freeze lock mismatch"):
        report(tmp_path, [p.name for p in runs])
    freeze_path.write_bytes(frozen_before)
    lock_path.write_bytes(locked_before)
    with pytest.raises(ValueError, match="Frozen protocol changed"):
        profile = tmp_path / "configs/profiles/rmm_falsification_v1/fixed.yaml"
        profile.write_text(profile.read_text() + "\n# tampered\n")
        report(tmp_path, [p.name for p in runs])
    shutil.copyfile(ROOT / "configs/profiles/rmm_falsification_v1/fixed.yaml", profile)
    record = next(p for p in runs[0].glob("*/result.json"))
    record.write_text(record.read_text() + "\n")
    with pytest.raises(ValueError, match="corrupt"):
        report(tmp_path, [p.name for p in runs])
