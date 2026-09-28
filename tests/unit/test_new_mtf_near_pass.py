"""Near-pass boundaries, immutable reclassification, and unchanged execution gate."""

import json

import pandas as pd
import pytest

from quant_lab.new_mtf_classification import classify_existing, digest, select_source
from quant_lab.new_mtf_reporting import CRITERIA, classify_research, eligibility
from quant_lab.new_mtf_runner import matrix
from quant_lab.new_mtf_watchlist import RULES, write_classification


def metrics():
    return pd.DataFrame(
        [
            config
            | {
                "partition": p,
                "costs": cost,
                "return_pct": 2.0,
                "profit_factor": 1.2,
                "expectancy": 0.2,
                "sharpe": 0.3,
                "max_drawdown_pct": 15.0,
                "closed_trades": 110,
                "total_costs": 10.0,
            }
            for config in matrix()
            for p in ["full", "final_holdout"] + [f"wf_{i:02}_test" for i in range(22)]
            for cost in ("base", "adverse")
        ]
    )


def change(table, partition, cost, column, value):
    table.loc[(table.partition == partition) & (table.costs == cost), column] = value


@pytest.mark.parametrize(
    "failed,label", [(0, "RESEARCH_PASS"), (1, "NEAR_PASS"), (2, "NEAR_PASS"), (3, "RESEARCH_FAIL")]
)
def test_precedence_and_maximum_failures(failed, label):
    table = metrics()
    edits = [
        ("full", "base", "profit_factor", 1.05),
        ("full", "base", "max_drawdown_pct", 22),
        ("full", "base", "closed_trades", 80),
    ]
    for edit in edits[:failed]:
        change(table, *edit)
    result = classify_research(table)
    assert result.research_classification.eq(label).all()
    assert result.failed_pass_criteria_count.eq(failed).all()
    assert result.research_pass.eq(failed == 0).all()
    assert len(eligibility(result)["eligible"]) == (8 if failed == 0 else 0)
    assert len(RULES) == 13
    assert all(result[c].dtype == bool for _, c, _ in RULES.values())
    pd.testing.assert_frame_equal(result, classify_research(table.sample(frac=1, random_state=17)))


@pytest.mark.parametrize(
    "partition,cost,column,value",
    [
        ("full", "base", "return_pct", -1),
        ("full", "base", "return_pct", 0),
        ("full", "base", "expectancy", -0.1),
        ("full", "base", "sharpe", 0),
        ("full", "base", "profit_factor", 1.029),
        ("full", "base", "max_drawdown_pct", 25.01),
        ("full", "base", "closed_trades", 74),
        ("final_holdout", "base", "closed_trades", 14),
        ("full", "adverse", "return_pct", -20),
        ("full", "adverse", "profit_factor", 0.799),
        ("final_holdout", "base", "profit_factor", float("nan")),
    ],
)
def test_critical_minimums(partition, cost, column, value):
    table = metrics()
    change(table, partition, cost, column, value)
    assert classify_research(table).research_classification.eq("RESEARCH_FAIL").all()


@pytest.mark.parametrize(
    "partition,cost,column,value",
    [
        ("full", "base", "profit_factor", 1.03),
        ("full", "base", "max_drawdown_pct", 25),
        ("full", "base", "closed_trades", 75),
        ("final_holdout", "base", "closed_trades", 15),
        ("full", "adverse", "return_pct", -19.99),
        ("full", "adverse", "profit_factor", 0.8),
    ],
)
def test_inclusive_minimum_boundaries(partition, cost, column, value):
    table = metrics()
    change(table, partition, cost, column, value)
    result = classify_research(table)
    assert result.research_classification.eq("NEAR_PASS").all()
    assert result.failed_pass_criteria_count.eq(1).all()


def test_fold_minimum_and_integrity_gate():
    table = metrics()
    for i in range(7, 22):
        change(table, f"wf_{i:02}_test", "base", "return_pct", -1)
    assert classify_research(table).research_classification.eq("NEAR_PASS").all()
    change(table, "wf_06_test", "base", "return_pct", 0)
    assert classify_research(table).research_classification.eq("RESEARCH_FAIL").all()
    change(table, "wf_06_test", "base", "return_pct", 1)
    incomplete = classify_research(table[table.partition != "wf_21_test"])
    assert incomplete.failed_pass_criteria_count.eq(1).all()
    assert incomplete.research_classification.eq("RESEARCH_FAIL").all()


def test_companion_report_preserves_source_and_detects_tampering(tmp_path, monkeypatch):
    import quant_lab.new_mtf_classification as module

    monkeypatch.setattr(module, "provenance", lambda repo: {"code_sha256": "new-report-code"})
    source = tmp_path / "results/new_mtf_strategies/a-run"
    child = source / "phase_a/batch"
    child.mkdir(parents=True)
    table = metrics()
    change(table, "full", "base", "profit_factor", 1.05)
    table.to_csv(child / "results.csv", index=False)
    files = {
        "phase.json": {"phase": "a", "batch": "phase_a/batch"},
        "verification.json": {"status": "completed"},
        "plan.json": {"phase": "a", "research_criteria": CRITERIA},
        "provenance.json": {"code_sha256": "old-strategy-code"},
        "phase_a/batch/verification.json": {"status": "completed"},
        "phase_a/batch/v4_eligibility.json": eligibility(classify_research(table)),
    }
    for name, value in files.items():
        (source / name).write_text(json.dumps(value))
    (source / "summary.md").write_text("Frozen summary")
    original = {str(p.relative_to(source)): digest(p) for p in source.rglob("*") if p.is_file()}
    (source / "artifact_manifest.json").write_text(json.dumps(original))
    original["artifact_manifest.json"] = digest(source / "artifact_manifest.json")
    output = classify_existing(tmp_path, "a-run")
    assert len(pd.read_csv(output / "near_pass.csv")) == 16
    assert "NEAR_PASS WATCHLIST" in (output / "summary.md").read_text(encoding="utf-8")
    assert all(digest(source / name) == sha for name, sha in original.items())
    assert select_source(tmp_path)[0] == source
    second = classify_existing(tmp_path, "a-run")
    assert second != output
    assert digest(second / "research_classification.csv") == digest(
        output / "research_classification.csv"
    )
    with pytest.raises(ValueError, match="run_id"):
        select_source(tmp_path, "../a-run")
    (child / "results.csv").write_text("tampered")
    with pytest.raises(ValueError, match="changed"):
        classify_existing(tmp_path, "a-run")


def test_output_empty_watchlist_has_headers_and_does_not_overwrite(tmp_path):
    classified = classify_research(metrics())
    text = write_classification(tmp_path, classified)
    assert pd.read_csv(tmp_path / "near_pass.csv").empty
    assert "No NEAR_PASS" in text
    with pytest.raises(FileExistsError):
        write_classification(tmp_path, classified)
