"""Gate boundary regressions, immutable receipts and source-run integrity."""

import json
from pathlib import Path

import pandas as pd
import pytest

from quant_lab.new_mtf_preflight import CHECKS, require_preflight
from quant_lab.new_mtf_reporting import classify_research, comparisons, eligibility
from quant_lab.new_mtf_runner import matrix, phase_a_source, run_phase, seal


def rows(configs=None):
    result = []
    for config in configs or matrix():
        for partition in ["full", "train", "validation", "test", "final_holdout"] + [
            f"wf_{i:02}_test" for i in range(22)
        ]:
            for cost in ("zero", "base", "adverse"):
                result.append(
                    config
                    | {
                        "partition": partition,
                        "costs": cost,
                        "return_pct": 1.0,
                        "profit_factor": 1.1,
                        "expectancy": 0.1,
                        "sharpe": 0.1,
                        "max_drawdown_pct": 20.0,
                        "closed_trades": 100,
                        "total_costs": 10.0,
                    }
                )
    return pd.DataFrame(result)


@pytest.mark.parametrize(
    "partition,cost,column,value,passes",
    [
        ("full", "base", "return_pct", 0, False),
        ("full", "base", "profit_factor", 1.10, True),
        ("full", "base", "profit_factor", 1.099, False),
        ("full", "base", "expectancy", 0, False),
        ("full", "base", "sharpe", 0, False),
        ("full", "base", "max_drawdown_pct", 20.01, False),
        ("full", "base", "closed_trades", 99, False),
        ("final_holdout", "base", "closed_trades", 20, True),
        ("final_holdout", "base", "closed_trades", 19, False),
        ("final_holdout", "base", "return_pct", 0, True),
        ("final_holdout", "base", "expectancy", 0, False),
        ("final_holdout", "base", "profit_factor", 1, True),
        ("final_holdout", "base", "profit_factor", 0.99, False),
        ("full", "adverse", "return_pct", -10, False),
        ("full", "adverse", "return_pct", -9.99, True),
        ("full", "adverse", "profit_factor", 0.90, True),
        ("full", "adverse", "profit_factor", 0.89, False),
        ("full", "base", "profit_factor", float("nan"), False),
        ("full", "base", "profit_factor", float("inf"), False),
    ],
)
def test_all_research_thresholds(partition, cost, column, value, passes):
    table = rows(matrix()[:1])
    table.loc[(table.partition == partition) & (table.costs == cost), column] = value
    assert bool(classify_research(table).research_pass.iloc[0]) is passes


def test_fold_count_missing_duplicates_and_phase_b_deduplication():
    table = rows()
    table.loc[table.partition.isin([f"wf_{i:02}_test" for i in range(9, 22)]), "return_pct"] = -1
    classified = classify_research(table)
    assert classified.research_pass.all()
    assert classified.positive_folds.eq(9).all()
    assert len(eligibility(classified)["eligible"]) == 8
    table.loc[table.partition == "wf_08_test", "return_pct"] = 0
    assert not classify_research(table).research_pass.any()
    assert not eligibility(classify_research(table))["eligible"]
    assert not classify_research(table[table.partition != "wf_21_test"]).research_pass.any()
    with pytest.raises(ValueError, match="Duplicate"):
        classify_research(pd.concat([table, table.iloc[:1]]))
    with pytest.raises(ValueError, match="16"):
        eligibility(classified.iloc[:-1])
    with pytest.raises(ValueError, match="Missing"):
        classify_research(table[table.partition != "final_holdout"])


def test_v4_is_evaluated_independently_and_deltas_are_signed():
    a = classify_research(rows())
    b = rows(matrix(("V4",)))
    b.loc[(b.partition == "full") & (b.costs == "base"), "return_pct"] = -1
    b = classify_research(b)
    assert not b.research_pass.any()
    delta = comparisons(pd.concat([a, b]), "V4")
    assert delta.baseline.eq("V1").all()
    assert delta.delta_return.eq(-2).all()
    assert not delta.improved_return.any()


def test_missing_failed_and_stale_preflight(tmp_path, monkeypatch):
    import quant_lab.new_mtf_preflight as module

    monkeypatch.setattr(module, "environment", lambda code: {"runtime": "test"})
    code = {"code_sha256": "abc"}
    with pytest.raises(ValueError, match="Missing"):
        require_preflight(tmp_path, code)
    folder = tmp_path / "reports/new_mtf_strategies/preflight"
    folder.mkdir(parents=True)
    record = {
        "passed": True,
        "code_unchanged": True,
        "code_sha256": "abc",
        "environment": {"runtime": "test"},
        "checks": {k: {"exit_code": 0} for k in CHECKS},
    }
    path = folder / "receipt.json"
    path.write_text(json.dumps(record))
    assert require_preflight(tmp_path, code)["passed"]
    with pytest.raises(ValueError, match="stale"):
        require_preflight(tmp_path, {"code_sha256": "different"})
    record["checks"]["pip check"]["exit_code"] = 1
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="stale"):
        require_preflight(tmp_path, code)


def test_phase_b_rechecks_artifacts_and_does_not_trust_csv_pass(tmp_path):
    root = tmp_path / "a"
    child = root / "phase_a/run"
    child.mkdir(parents=True)
    table = rows()
    table.to_csv(child / "results.csv", index=False)
    (child / "v4_eligibility.json").write_text(json.dumps(eligibility(classify_research(table))))
    for name, value in {
        "plan": {},
        "provenance": {"code_sha256": "abc"},
        "phase": {"phase": "a", "batch": "phase_a/run"},
        "verification": {"status": "completed"},
    }.items():
        (root / (name + ".json")).write_text(json.dumps(value))
    seal(root)
    _, _, gate = phase_a_source(tmp_path, root, {"code_sha256": "abc"})
    assert len(gate["eligible"]) == 8
    with pytest.raises(ValueError, match="differs"):
        phase_a_source(tmp_path, root, {"code_sha256": "other"})
    (child / "results.csv").write_text("tampered")
    with pytest.raises(ValueError, match="changed"):
        phase_a_source(tmp_path, root, {"code_sha256": "abc"})


def test_phase_a_to_b_selection_reporting_and_immutable_source(tmp_path, monkeypatch):
    """Exercise real orchestration/reporting with metric fixtures, not backtests."""
    import quant_lab.new_mtf_runner as module

    code = {"code_sha256": "synthetic", "files": {}}
    monkeypatch.setattr(module, "provenance", lambda *a: code)
    monkeypatch.setattr(module, "matched_data", lambda *a: {})
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/new-mtf-strategies.md").write_text("synthetic protocol")
    called = []

    def fake_batch(repo, name, data, configs, protocol, code):
        called.append(configs)
        folder = Path(name) / "synthetic_batch"
        folder.mkdir(parents=True)
        table = rows(configs)
        selected = (table.asset == "BTCUSDT") & (table.family == "keltner_breakout")
        table.loc[~selected, "closed_trades"] = 0
        table.to_csv(folder / "results.csv", index=False)
        historical = table[(table.partition == "full") & (table.costs == "base")].copy()
        historical["classification"] = "DIAGNOSTIC_ONLY"
        historical.to_csv(folder / "comparison.csv", index=False)
        return folder, historical

    monkeypatch.setattr(module, "run_batch", fake_batch)
    reference = {"splits": [], "folds": [], "settings": {}, "matched_audit": {}}
    a = run_phase(tmp_path, "a", code, {}, reference, {}, {})
    from quant_lab.new_mtf_runner import sha

    before = {str(p): sha(p) for p in a.rglob("*") if p.is_file()}
    b = run_phase(tmp_path, "b", code, {}, reference, {}, {}, a)
    assert len(called[0]) == 16
    assert called[1] == matrix(("V4",), [("BTCUSDT", "keltner_breakout")])
    assert {str(p): sha(p) for p in a.rglob("*") if p.is_file()} == before
    phase = json.loads((b / "phase.json").read_text())
    delta = pd.read_csv(b / phase["batch"] / "architecture_deltas.csv")
    assert delta.delta_return.iloc[0] == 0
    assert delta.baseline.iloc[0] == "V1"
    assert (b / "artifact_manifest.json").exists()
