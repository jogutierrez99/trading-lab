"""Strict boundary checks for the manual step4.3 execution plan."""

import json

import pytest

from trading_lab_orchestration.execution_contracts import ExecutionPlan


def plan(tmp_path):
    return {
        "schema_version": "1.0",
        "experiment": str(tmp_path / "experiment.yaml"),
        "experiment_sha256": "0" * 64,
        "protocol": "StudyBackend v1 / lab_experiment_v1",
        "scope": "SYNTHETIC_TECHNICAL",
        "all_declared_periods_authorized": True,
        "review_note": "Synthetic fixture, no holdout",
        "enable_execution_copy": True,
        "datasets": [
            {
                "path": str(tmp_path / "dataset"),
                "dataset_id": "0" * 64,
                "manifest_sha256": "0" * 64,
                "parquet_sha256": "0" * 64,
                "kind": "SYNTHETIC",
                "provenance_note": "Formula and source pinned",
                "provenance_files": {str(tmp_path / "generator.py"): "0" * 64},
            }
        ],
        "max_wall_seconds": 120,
        "validation_timeout_seconds": 60,
        "max_backtests": 3,
        "max_candles": 244,
        "max_dataset_bytes": 1000000,
    }


@pytest.mark.parametrize(
    "update",
    [
        {"schema_version": "2.0"},
        {"protocol": "arbitrary command"},
        {"scope": "TRAIN_ONLY"},
        {"all_declared_periods_authorized": False},
        {"max_backtests": 101},
        {"max_candles": 0},
        {"max_wall_seconds": True},
        {"max_wall_seconds": 3601},
        {"max_dataset_bytes": 0},
        {"validation_timeout_seconds": 301},
        {"command": ["codex"]},
        {"datasets": []},
    ],
)
def test_invalid_execution_plan(tmp_path, update):
    with pytest.raises(ValueError):
        ExecutionPlan.model_validate_json(json.dumps(plan(tmp_path) | update))


@pytest.mark.parametrize(
    "missing", ["protocol", "scope", "max_wall_seconds", "max_backtests", "review_note"]
)
def test_incomplete_execution_plan(tmp_path, missing):
    raw = plan(tmp_path)
    raw.pop(missing)
    with pytest.raises(ValueError):
        ExecutionPlan.model_validate_json(json.dumps(raw))


def test_valid_versioned_execution_plan(tmp_path):
    assert ExecutionPlan.model_validate_json(json.dumps(plan(tmp_path))).max_backtests == 3


@pytest.mark.parametrize(
    "update",
    [
        {"periods": ["train", "test"]},
        {"periods": ["train", "validation", "test"]},
        {"all_declared_periods_authorized": True},
        {"max_backtests": 25},
    ],
)
def test_rmm_plan_cannot_authorize_test_or_more_cases(tmp_path, update):
    comparison = {
        "task_id": "task_fixture",
        "candidate_id": "cand_fixture",
        "hypothesis_sha256": "0" * 64,
        "baseline_commit": "0" * 40,
        "baseline_files": {"baseline.yaml": "0" * 64},
        "periods": ["train", "validation"],
    }
    raw = plan(tmp_path) | {
        "scope": "RMM_TRAIN_VALIDATION",
        "all_declared_periods_authorized": False,
        "max_backtests": 24,
        "comparison": comparison,
    }
    assert ExecutionPlan.model_validate_json(json.dumps(raw)).comparison.periods == (
        "train",
        "validation",
    )
    for key, value in update.items():
        (comparison if key == "periods" else raw)[key] = value
    with pytest.raises(ValueError):
        ExecutionPlan.model_validate_json(json.dumps(raw))
