import copy
from pathlib import Path

import pytest

from quant_lab.config import load_yaml
from quant_lab.lab_classification import classify_configuration, oos_count, research_stage, wf_stage
from quant_lab.lab_classification_policy import ClassificationPolicy
from quant_lab.lab_schema import Experiment

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def policy():
    return load_yaml(ROOT / "configs/research/lab_classification_v1.yaml", ClassificationPolicy)


@pytest.fixture
def evidence():
    exp = load_yaml(ROOT / "configs/experiments/trend_rsi_pullback_v1_single_tf.yaml", Experiment)
    rows = []
    for label, period in exp.validation.periods():
        for scenario in ("base", "adverse"):
            rows.append(
                {
                    "configuration_id": "fixed",
                    "backtest_id": f"{label}_{scenario}",
                    "period": label,
                    "scenario": scenario,
                    "status": "completed",
                    "start": period.start.isoformat(),
                    "end": period.end.isoformat(),
                    "closed_trades": 20,
                    "return_pct": 2.0,
                    "profit_factor": 1.5,
                    "sharpe": 0.5,
                    "expectancy": 1.0,
                    "max_drawdown_pct": 5.0,
                }
            )
    return rows, exp.validation.model_dump(mode="json")["walk_forward"]


def test_all_stages_and_nonoverlapping_count(policy, evidence):
    rows, folds = evidence
    got = classify_configuration(rows, policy, folds, True)
    assert got["research_classification"] == "PAPER_TRADING_CANDIDATE"
    assert got["oos_evidence"]["trades"] == 100
    assert got["oos_evidence"]["excluded_periods"] == ["validation"]
    assert "train" not in got["oos_evidence"]["included_base_periods"]


@pytest.mark.parametrize(
    "metric",
    ["return_pct", "profit_factor", "sharpe", "expectancy", "closed_trades", "max_drawdown_pct"],
)
@pytest.mark.parametrize("value", [-999.0, None, 999999.0])
def test_research_stage_is_invariant_to_every_test_metric(policy, evidence, metric, value):
    rows, folds = evidence
    before = classify_configuration(rows, policy, folds, True)
    mutated = copy.deepcopy(rows)
    for r in mutated:
        if r["period"] == "test":
            r[metric] = value
    after = classify_configuration(mutated, policy, folds, True)
    for field in ("VALID", "RESEARCH_PASS", "research_reasons", "research_evidence_sha256"):
        assert after[field] == before[field]


def test_research_has_no_test_dependency_even_when_test_absent_or_malformed(policy, evidence):
    rows, _ = evidence
    before = research_stage(rows, policy, True)
    no_test = [r for r in rows if r["period"] != "test"]
    assert research_stage(no_test, policy, True) == before
    assert (
        research_stage(no_test + [{"period": "test", "anything": object()}], policy, True) == before
    )


@pytest.mark.parametrize(
    "period,scenario,metric,value",
    [
        ("train", "base", "closed_trades", 14),
        ("train", "base", "profit_factor", 1.09),
        ("train", "base", "sharpe", 0.24),
        ("train", "base", "expectancy", -0.01),
        ("train", "base", "max_drawdown_pct", 15.01),
        ("validation", "base", "closed_trades", 4),
        ("validation", "base", "profit_factor", 1.04),
        ("validation", "base", "sharpe", 0.14),
        ("validation", "adverse", "return_pct", 0.0),
        ("validation", "adverse", "profit_factor", 0.99),
        ("validation", "adverse", "expectancy", -0.01),
    ],
)
def test_research_economic_fail_stays_technically_valid(
    policy, evidence, period, scenario, metric, value
):
    rows, folds = evidence
    next(r for r in rows if (r["period"], r["scenario"]) == (period, scenario))[metric] = value
    got = classify_configuration(rows, policy, folds, True)
    assert got["research_classification"] == "VALID"
    assert got["oos_reasons"] == ["not_evaluated_before_research_pass"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("closed_trades", 0),
        ("status", "failed"),
        ("sharpe", None),
        ("profit_factor", float("inf")),
        ("error", "internal"),
    ],
)
def test_technical_fail(policy, evidence, field, value):
    rows, folds = evidence
    rows[0][field] = value
    assert classify_configuration(rows, policy, folds, True)["research_classification"] == "FAIL"
    assert classify_configuration(rows, policy, folds, False)["research_classification"] == "FAIL"


@pytest.mark.parametrize(
    "scenario,metric,value",
    [
        ("base", "closed_trades", 9),
        ("base", "return_pct", 0.0),
        ("base", "profit_factor", 1.09),
        ("base", "sharpe", 0.29),
        ("base", "expectancy", 0.0),
        ("base", "max_drawdown_pct", 15.01),
        ("adverse", "return_pct", 0.0),
        ("adverse", "profit_factor", 0.99),
        ("adverse", "expectancy", -0.01),
    ],
)
def test_oos_gates_only_after_research(policy, evidence, scenario, metric, value):
    rows, folds = evidence
    next(r for r in rows if (r["period"], r["scenario"]) == ("test", scenario))[metric] = value
    got = classify_configuration(rows, policy, folds, True)
    assert got["RESEARCH_PASS"]
    assert got["research_classification"] == "RESEARCH_PASS"


def test_wf_does_not_use_train_or_one_spectacular_fold(policy, evidence):
    rows, folds = evidence
    for r in rows:
        if r["period"].startswith("wf_") and r["period"].endswith("_train"):
            r.update(return_pct=1e9, expectancy=1e9)
        if r["period"].startswith("wf_") and r["period"].endswith("_test"):
            r.update(
                return_pct=10000.0 if r["period"] == "wf_0_test" else -1.0,
                expectancy=10000.0 if r["period"] == "wf_0_test" else -1.0,
            )
    got = classify_configuration(rows, policy, folds, True)
    assert got["research_classification"] == "OOS_PASS"
    assert got["robustness"]["median_return_pct"] == -1.0


def test_missing_fixed_wf_is_not_borrowed_from_other_candidates(policy, evidence):
    rows, folds = evidence
    fixed = [r for r in rows if r["period"] != "wf_2_test"]
    assert not wf_stage(fixed, policy, folds)["pass"]
    assert wf_stage(rows, policy, folds)["pass"]


def test_paper_requires_oos_sample_and_cost_survival(policy, evidence):
    rows, folds = evidence
    stricter = policy.model_copy(update={"minimum_total_oos_trades": 101})
    assert (
        classify_configuration(rows, stricter, folds, True)["research_classification"]
        == "ROBUST_PASS"
    )
    for r in rows:
        if r["period"] in {"wf_0_test", "wf_1_test", "wf_2_test"} and r["scenario"] == "adverse":
            r["return_pct"] = -1.0
    assert (
        classify_configuration(rows, policy, folds, True)["research_classification"] == "OOS_PASS"
    )
    assert oos_count(rows)["trades"] == 100
