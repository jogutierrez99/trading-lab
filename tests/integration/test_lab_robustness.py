"""Tiny fixtures for phase-two scheduling/provenance, not strategy profitability."""

import copy
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
from test_trend_volatility_breakout_lab import save
from test_trend_volatility_breakout_lab import small as small_fixture

from quant_lab.config import load_yaml
from quant_lab.lab_classification import classify, classify_evidence
from quant_lab.lab_classification_policy import ClassificationPolicy
from quant_lab.lab_cli import main
from quant_lab.lab_evidence import completed_run
from quant_lab.lab_publish import publish
from quant_lab.lab_robustness import checked_rows, latest_robustness, records, robust
from quant_lab.lab_runner import run

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "configs/research/lab_classification_v1.yaml"


def fingerprint(path):
    return {
        p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in path.rglob("*")
        if p.is_file()
    }


@pytest.fixture
def saved(tmp_path, monkeypatch):
    import quant_lab.lab_robustness as robustness
    import quant_lab.lab_runner as runner

    root, raw, frame = small_fixture.__wrapped__(tmp_path)
    raw["modes"] = ["LONG_ONLY"]
    raw["strategy_parameters"]["trend_length"] = [8, 10]
    points = [frame.index[i].to_pydatetime() for i in (100, 200, 225, 250, 275, 300)]
    raw["validation"]["walk_forward"] = [
        {
            "train": {"start": points[0], "end": points[i + 1]},
            "test": {"start": points[i + 1], "end": points[i + 2]},
        }
        for i in range(4)
    ]
    # Controlled metrics exercise gates and scheduling, not economic claims.
    real_summary = runner.summarize

    def metrics(result):
        return real_summary(result) | {
            "closed_trades": 20,
            "return_pct": 2.0,
            "profit_factor": 1.5,
            "sharpe": 0.5,
            "expectancy": 1.0,
            "max_drawdown_pct": 5.0,
        }

    monkeypatch.setattr(runner, "summarize", metrics)
    monkeypatch.setattr(robustness, "summarize", metrics)

    def ranking(row, exp):
        preferred = 8
        if row["period"].startswith("wf_"):
            preferred = 8 if int(row["period"].split("_")[1]) % 2 == 0 else 10
        return row["parameters"]["trend_length"] != preferred, row["configuration_id"]

    monkeypatch.setattr(runner, "rank_key", ranking)
    path, exp = save(root, raw, frame)
    source = run(path, exp, root)
    return root, exp, source


def test_only_missing_fixed_tests_eligible_candidates_reuse_and_reclassify(saved, monkeypatch):
    import quant_lab.lab_robustness as module

    root, exp, source = saved
    evidence = completed_run(root, exp.experiment_id)
    policy = load_yaml(POLICY, ClassificationPolicy)
    original = classify_evidence(evidence, policy)
    assert all(c["OOS_PASS"] and not c["ROBUST_PASS"] for c in original["candidates"])
    assert original["walk_forward_selection"][0]["pass"]
    before = fingerprint(source)
    calls = []
    real_evaluate = module.evaluate

    def evaluate(*args):
        calls.append((args[4], args[5], args[6]))
        return real_evaluate(*args)

    monkeypatch.setattr(module, "evaluate", evaluate)
    result = robust(root, source.name, POLICY)
    assert result["eligible_candidates"] == 2
    assert result["executed_backtests"] == 8 and result["reused_backtests"] == 8
    assert len(calls) == 8
    assert all(
        period.model_dump() in [f.test.model_dump() for f in exp.validation.walk_forward]
        for _, period, _ in calls
    )
    assert {p["trend_length"] for p, _, _ in calls} == {8, 10}
    fixed = latest_robustness(root, completed_run(root, source.name))
    assert len(fixed[2]) == 16
    classification = json.loads(
        (Path(result["classification_directory"]) / "classification.json").read_text()
    )
    assert all(
        c["ROBUST_PASS"] and c["PAPER_TRADING_CANDIDATE"] for c in classification["candidates"]
    )
    assert classification["walk_forward_selection"] == original["walk_forward_selection"]
    assert all(len(c["robustness"]["wf_tests"]) == 4 for c in classification["candidates"])
    assert fingerprint(source) == before
    monkeypatch.setattr(module, "evaluate", lambda *a: pytest.fail("Repeated robustness rerun"))
    again = robust(root, exp.experiment_id, POLICY)
    assert again["executed_backtests"] == 0 and again["reused_backtests"] == 16
    assert fingerprint(source) == before
    assert main(["--root", str(root), "robust", exp.experiment_id, "--policy", str(POLICY)]) == 0


def test_compact_publication_contains_fixed_evidence_without_heavy_artifacts(saved):
    root, exp, _ = saved
    robust(root, exp.experiment_id, POLICY)
    classify(root, exp.experiment_id, POLICY)
    publication = publish(root, exp.experiment_id)
    assert {
        "robustness.json",
        "robustness_summary.md",
        "robustness_metrics_compact.csv",
        "classification.json",
    } <= set(publication["published"])
    destination = Path(publication["publication_directory"])
    assert len(pd.read_csv(destination / "robustness_metrics_compact.csv")) == 16
    assert not list(destination.rglob("*.parquet")) and not list(destination.rglob("*.sqlite"))
    assert not list(destination.rglob("result.json"))


@pytest.mark.parametrize("failed_gate", ["research", "oos"])
def test_ineligible_fixed_candidate_is_never_scheduled(saved, failed_gate):
    root, exp, source = saved
    table = pd.read_csv(source / "metrics.csv")
    identity = table.configuration_id.iloc[0]
    if failed_gate == "research":
        table.loc[(table.configuration_id == identity) & (table.period == "train"), "sharpe"] = None
    else:
        table.loc[
            (table.configuration_id == identity) & (table.period == "test"), "return_pct"
        ] = -1.0
    table.to_csv(source / "metrics.csv", index=False)
    result = robust(root, exp.experiment_id, POLICY)
    assert result["eligible_candidates"] == 1 and result["executed_backtests"] == 4
    fixed = latest_robustness(root, completed_run(root, source.name))
    assert all(r["configuration_id"] != identity for r in fixed[2])


@pytest.mark.parametrize(
    "corruption", ["equity", "result", "ledger", "metrics", "code", "config", "dataset"]
)
def test_incompatible_or_corrupt_reuse_rejected_without_backtests(saved, monkeypatch, corruption):
    import quant_lab.lab_robustness as module

    root, exp, source = saved
    row = records(pd.read_csv(source / "metrics.csv"))[0]
    if corruption in {"equity", "result"}:
        name = "equity.parquet" if corruption == "equity" else "result.json"
        (source / row["backtest_id"] / name).write_bytes(b"bad")
    elif corruption == "ledger":
        import sqlite3

        with sqlite3.connect(source / "ledger.sqlite") as db:
            db.execute("UPDATE experiments SET result_sha256='bad'")
    elif corruption == "metrics":
        table = pd.read_csv(source / "metrics.csv")
        table.loc[0, "return_pct"] = 99.0
        table.to_csv(source / "metrics.csv", index=False)
    elif corruption == "code":
        (root / "src").mkdir()
        (root / "src/change.py").write_text("# different execution code")
    elif corruption == "config":
        profile = root / "configs/strategies/trend_volatility_breakout_v1.yaml"
        profile.write_text(profile.read_text().replace("reward_risk: 2.0", "reward_risk: 2.5"))
    else:
        next((root / "data").glob("*/candles.parquet")).write_bytes(b"bad")
    monkeypatch.setattr(module, "evaluate", lambda *a: pytest.fail("Corrupt source rerun"))
    with pytest.raises(ValueError):
        robust(root, exp.experiment_id, POLICY)


def test_corrupt_supplement_and_changed_parameters_or_folds_rejected(saved, monkeypatch):
    root, exp, source = saved
    result = robust(root, exp.experiment_id, POLICY)
    evidence = completed_run(root, source.name)
    fixed = latest_robustness(root, evidence)
    rows = copy.deepcopy(fixed[2])
    rows[0]["parameters"] = json.dumps({"trend_length": 999})
    with pytest.raises(ValueError, match="parameters"):
        checked_rows(evidence, rows)
    rows = copy.deepcopy(fixed[2])
    rows[0]["start"] = "2022-01-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="dates"):
        checked_rows(evidence, rows)
    rows = copy.deepcopy(fixed[2])
    rows[0]["configuration_id"] = "unrelated"
    with pytest.raises(ValueError, match="identity"):
        checked_rows(evidence, rows)
    (Path(result["robustness_directory"]) / "metrics.csv").write_bytes(b"bad")
    with pytest.raises(ValueError, match="hash"):
        robust(root, exp.experiment_id, POLICY)
    with pytest.raises(ValueError, match="hash"):
        publish(root, exp.experiment_id)


def test_failed_supplement_is_not_used_and_missing_work_can_retry(saved, monkeypatch):
    import quant_lab.lab_robustness as module

    root, exp, source = saved
    original = module.evaluate

    calls = []

    def fail(*args):
        calls.append(args)
        if len(calls) == 2:
            raise RuntimeError("fixture interruption")
        return original(*args)

    monkeypatch.setattr(module, "evaluate", fail)
    with pytest.raises(RuntimeError, match="interruption"):
        robust(root, exp.experiment_id, POLICY)
    assert latest_robustness(root, completed_run(root, source.name)) is None
    monkeypatch.setattr(module, "evaluate", original)
    result = robust(root, exp.experiment_id, POLICY)
    assert result["executed_backtests"] == 7 and result["reused_backtests"] == 9


def test_zero_eligible_does_not_prepare_or_evaluate(saved, monkeypatch):
    import quant_lab.lab_robustness as module

    root, exp, source = saved
    frame = pd.read_csv(source / "metrics.csv")
    frame.loc[frame.period == "test", "return_pct"] = -1.0
    frame.to_csv(source / "metrics.csv", index=False)
    monkeypatch.setattr(
        module, "execution_context", lambda *a: pytest.fail("Zero eligible prepare")
    )
    monkeypatch.setattr(module, "evaluate", lambda *a: pytest.fail("Zero eligible backtest"))
    result = robust(root, exp.experiment_id, POLICY)
    assert result["message"] == "0 candidates eligible for robustness evaluation"
    assert result["executed_backtests"] == result["eligible_candidates"] == 0
    assert publish(root, source.name)["published"]
