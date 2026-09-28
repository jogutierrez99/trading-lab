"""Synthetic orchestration/reporting and hard baseline/preflight gates."""

import io
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from quant_lab import optional_fill_preflight as preflight_module
from quant_lab import optional_fill_runner as runner
from quant_lab.backtest import BacktestResult
from quant_lab.execution_policies.optional_15m_fill import fill_metrics
from quant_lab.experiments import write_json
from quant_lab.new_mtf_preflight import CHECKS
from quant_lab.new_mtf_runner import read_json
from quant_lab.optional_fill_preflight import RECEIPTS, require_preflight
from quant_lab.optional_fill_protocol import load_protocol
from quant_lab.optional_fill_reporting import report


def test_preflight_preserves_non_utf8_failure_and_writes_receipt(tmp_path, monkeypatch):
    protocol = load_protocol(Path.cwd())
    real_run = subprocess.run
    monkeypatch.setattr(preflight_module, "CHECKS", ("ruff format --check .",))
    monkeypatch.setattr(preflight_module, "load_protocol", lambda *a: protocol)
    monkeypatch.setattr(preflight_module, "provenance", lambda *a: {"code_sha256": "same"})
    monkeypatch.setattr(preflight_module, "environment", lambda *a: {})
    monkeypatch.setattr(
        preflight_module,
        "isolated_test_environment",
        lambda: {"PYTEST_DEBUG_TEMPROOT": str(tmp_path)},
    )

    def emit_invalid_bytes(command, **kwargs):
        return real_run(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(b'failure \\x9d \\xe2\\x9d\\x8c');"
                " sys.exit(1)",
            ],
            **kwargs,
        )

    monkeypatch.setattr(preflight_module.subprocess, "run", emit_invalid_bytes)
    console = io.BytesIO()
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdout", io.TextIOWrapper(console, encoding="cp1252"))
        assert not preflight_module.preflight(tmp_path, technical_only=True)
        assert b"\\u274c" in console.getvalue()
    record = read_json(next((tmp_path / RECEIPTS).glob("*.json")))
    assert record["checks"]["ruff format --check ."] == {
        "exit_code": 1,
        "output": "failure \\x9d \u274c",
    }
    assert not record["passed"]


def test_reporting_all_six_pairs_and_failures_are_explicit(tmp_path):
    protocol = load_protocol(Path.cwd())
    rows = []
    stats = fill_metrics([]) | {
        "signals_total": 100,
        "optimized_entries": 50,
        "fallback_entries": 50,
        "optimization_rate": 0.5,
        "fallback_rate": 0.5,
        "trade_retention_rate": 1.0,
        "average_fill_improvement_pct": 0.1,
        "average_wait_minutes": 45.0,
        "median_wait_minutes": 60.0,
    }
    windows = (
        ["full", "train", "validation", "test", "final_holdout"]
        + [f"wf_{i:02}_test" for i in range(22)]
        + [f"segment_{i:02}" for i in range(29)]
    )
    for c in protocol.configurations:
        for variant in ("baseline", "optimized"):
            for partition in windows:
                for costs in ("zero", "base", "adverse"):
                    rows.append(
                        {
                            "asset": c.asset,
                            "family": c.family,
                            "architecture": c.architecture,
                            "variant": variant,
                            "partition": partition,
                            "costs": costs,
                            "return_pct": 20.0,
                            "max_drawdown_pct": 10.0,
                            "profit_factor": 1.4,
                            "expectancy": 2.0,
                            "closed_trades": 100,
                            "total_costs": 500.0,
                        }
                        | stats
                    )
    plan = {
        "config": protocol.model_dump(mode="json"),
        "code_sha256": "test",
        "expected_executions": 2016,
    }
    classified = report(tmp_path, rows, [{"status": "reproduced"}], plan, {})
    assert len(classified) == 6 and set(classified.classification) == {"FILL_IMPROVED"}
    assert len(pd.read_csv(tmp_path / "paired_comparison.csv")) == 1008
    text = (tmp_path / "ai_summary.md").read_text(encoding="utf-8")
    for title in (
        "Executive summary",
        "Main results",
        "Per configuration",
        "Execution behaviour",
        "Temporal robustness",
        "Classification reasons",
        "Research interpretation",
        "Next candidates",
    ):
        assert "## " + title in text
    assert "never restores" in text and "2016" in text
    failed_folder = tmp_path / "failed"
    failed_folder.mkdir()
    result = report(
        failed_folder,
        [],
        [],
        plan,
        {c.key: "BASELINE_REPRODUCTION_FAILED" for c in protocol.configurations},
    )
    assert set(result.classification) == {"FILL_WORSE"}
    assert result.reasons.str.contains("BASELINE_REPRODUCTION_FAILED").all()


def test_preflight_rejects_changed_code_or_config_or_incomplete_checks(tmp_path, monkeypatch):
    protocol = load_protocol(Path.cwd())
    monkeypatch.setattr(
        "quant_lab.optional_fill_preflight.environment", lambda code: {"runtime": 1}
    )
    record = {
        "passed": True,
        "code_unchanged": True,
        "code_sha256": "same",
        "environment": {"runtime": 1},
        "config": protocol.model_dump(mode="json"),
        "datasets_and_artifacts_verified": True,
        "checks": {k: {"exit_code": 0} for k in CHECKS},
    }
    folder = tmp_path / RECEIPTS
    folder.mkdir(parents=True)
    write_json(folder / "00.json", record)
    assert require_preflight(tmp_path, {"code_sha256": "same"}, protocol)
    for i, change in enumerate(
        (
            {"passed": False},
            {"code_sha256": "changed"},
            {"checks": {}},
            {"config": {}},
            {"datasets_and_artifacts_verified": False},
        ),
        1,
    ):
        write_json(folder / f"{i:02}.json", record | change)
        with pytest.raises(ValueError, match="preflight"):
            require_preflight(tmp_path, {"code_sha256": "same"}, protocol)


@pytest.mark.parametrize("fail_first", [False, True])
def test_runner_reproduces_before_optimization_and_aborts_only_failed_pair(
    tmp_path, monkeypatch, fail_first
):
    protocol = load_protocol(Path.cwd())
    monkeypatch.setattr(runner, "load_protocol", lambda *a: protocol)
    monkeypatch.setattr(runner, "provenance", lambda *a: {"code_sha256": "same", "files": {}})
    monkeypatch.setattr("quant_lab.optional_fill_preflight.require_preflight", lambda *a: {})
    start, end = pd.Timestamp("2020", tz="UTC"), pd.Timestamp("2020-01-02", tz="UTC")
    refs = {
        c.key: {("train", scenario): {"case": c.key} for scenario in ("zero", "base", "adverse")}
        for c in protocol.configurations
    }
    monkeypatch.setattr(
        runner,
        "context",
        lambda *a: (
            {c.asset: {} for c in protocol.configurations},
            [("train", start, end)],
            [],
            end,
            {k: [] for k in ("splits", "folds", "settings", "matched_audit")},
            {"new_mtf": tmp_path, "legacy_mtf": tmp_path},
            refs,
        ),
    )
    monkeypatch.setattr(runner, "inventory", lambda *a: [])
    monkeypatch.setattr(runner, "prepare_case", lambda data, case: case)
    monkeypatch.setattr(runner, "verify_source", lambda *a: tmp_path)
    index = pd.date_range(start, end, freq="h")
    equity, side = pd.Series(10000.0, index=index), pd.Series(0.0, index=index)
    result = BacktestResult((), equity, (), None, "long", "perpetual", side, 0.0)
    baseline_calls, optimized_calls = [], []

    def baseline(case, *args):
        baseline_calls.append(case)
        return result, side, []

    def optimized(prepared, case, *args):
        assert len(baseline_calls) == (16 if fail_first else 18)
        optimized_calls.append(case)
        return result, side, [], []

    monkeypatch.setattr(runner, "baseline_run", baseline)
    monkeypatch.setattr(runner, "optimized_run", optimized)
    monkeypatch.setattr(runner, "entry_stream", lambda *a: [])

    def compare(child, reference, *args):
        if fail_first and reference["case"] == protocol.configurations[0].key:
            raise ValueError("Baseline reproduction mismatch: fixture")
        return {"status": "reproduced"}

    monkeypatch.setattr(runner, "compare_baseline", compare)
    summaries = []
    monkeypatch.setattr(
        runner,
        "report",
        lambda folder, rows, reproduction, plan, failed: summaries.append(
            (rows, reproduction, failed)
        ),
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/optional-15m-fill.md").write_text("test", encoding="utf-8")
    folder, passed = runner.run(tmp_path)
    assert passed != fail_first
    assert len(optimized_calls) == (15 if fail_first else 18)
    assert (folder / "artifact_manifest.json").exists()
    assert (folder / "trade_pairs.csv").exists() and (folder / "trades.csv").exists()
    if fail_first:
        assert protocol.configurations[0].key not in optimized_calls
        assert "BASELINE_REPRODUCTION_FAILED" in next(iter(summaries[0][2].values()))
    else:
        assert len(summaries[0][0]) == 36
