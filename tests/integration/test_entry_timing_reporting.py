"""Offline reporting, preflight admission and abort-before-timing orchestration."""

from pathlib import Path

import pandas as pd
import pytest

from quant_lab import entry_timing_runner as runner
from quant_lab.entry_timing_execution import CASES
from quant_lab.entry_timing_preflight import RECEIPTS, require_preflight
from quant_lab.entry_timing_protocol import load_protocol
from quant_lab.entry_timing_reporting import finish
from quant_lab.execution_policies.timing_15m import timing_metrics
from quant_lab.experiments import write_json
from quant_lab.new_mtf_preflight import CHECKS


def test_reports_include_all_pairs_and_required_sections(tmp_path):
    rows = []
    stats = timing_metrics([])
    windows = (
        ["train", "validation", "test", "final_holdout", "full"]
        + [f"wf_{i:02}_test" for i in range(22)]
        + [f"segment_{i:02}" for i in range(29)]
    )
    for asset, family, architecture in CASES:
        for variant in ("baseline", "timing"):
            for partition in windows:
                for costs in ("zero", "base", "adverse"):
                    rows.append(
                        stats
                        | {
                            "asset": asset,
                            "family": family,
                            "architecture": architecture,
                            "variant": variant,
                            "partition": partition,
                            "costs": costs,
                            "return_pct": 20.0,
                            "max_drawdown_pct": 10.0,
                            "profit_factor": 1.4,
                            "expectancy": 2.0 if variant == "baseline" else 3.0,
                            "closed_trades": 100,
                            "total_costs": 500.0,
                            "signal_execution_rate": 0.5,
                        }
                    )
    finish(tmp_path, rows, {"code_sha256": "test"}, [{}] * 504)
    expected = {
        "results",
        "metrics",
        "paired_comparison",
        "segment_metrics",
        "fold_metrics",
        "holdout",
        "cost_sensitivity",
        "timing_metrics",
        "timing_classification",
    }
    assert all((tmp_path / (name + ".csv")).is_file() for name in expected)
    assert len(pd.read_csv(tmp_path / "results.csv")) == 1008
    assert len(pd.read_csv(tmp_path / "paired_comparison.csv")) == 504
    assert set(pd.read_csv(tmp_path / "timing_classification.csv").classification) == {
        "TIMING_IMPROVED"
    }
    text = (tmp_path / "ai_summary.md").read_text(encoding="utf-8")
    for heading in (
        "Executive summary",
        "Main results",
        "Supertrend V2",
        "ROC V2",
        "ROC V1",
        "Timing behaviour",
        "Temporal robustness",
        "Classification reasons",
        "Research interpretation",
        "Next research candidates",
    ):
        assert "## " + heading in text
    assert "entry timing" not in text.lower() or "1008" in text


def test_stale_failed_or_technical_preflight_rejected(tmp_path, monkeypatch):
    protocol = load_protocol(Path.cwd())
    monkeypatch.setattr("quant_lab.entry_timing_preflight.environment", lambda code: {"runtime": 1})
    record = {
        "passed": True,
        "code_unchanged": True,
        "code_sha256": "same",
        "environment": {"runtime": 1},
        "technical_only": False,
        "config": protocol.model_dump(mode="json"),
        "checks": {k: {"exit_code": 0} for k in CHECKS},
        "datasets_and_artifacts_verified": True,
        "baseline_reproduction": [{"status": "reproduced"}] * 3,
    }
    folder = tmp_path / RECEIPTS
    folder.mkdir(parents=True)
    write_json(folder / "00.json", record)
    assert require_preflight(tmp_path, {"code_sha256": "same"}, protocol)
    for i, change in enumerate(
        (
            {"technical_only": True},
            {"code_sha256": "changed"},
            {"passed": False},
            {"baseline_reproduction": []},
            {"datasets_and_artifacts_verified": False},
        ),
        1,
    ):
        write_json(folder / f"{i:02}.json", record | change)
        with pytest.raises(ValueError, match="preflight"):
            require_preflight(tmp_path, {"code_sha256": "same"}, protocol)


def test_baseline_mismatch_never_starts_timing(tmp_path, monkeypatch):
    protocol = load_protocol(Path.cwd())
    monkeypatch.setattr(runner, "load_protocol", lambda *a: protocol)
    monkeypatch.setattr(runner, "provenance", lambda *a: {"code_sha256": "same", "files": {}})
    monkeypatch.setattr("quant_lab.entry_timing_preflight.require_preflight", lambda *a: {})
    start, end = pd.Timestamp("2020", tz="UTC"), pd.Timestamp("2020-01-02", tz="UTC")
    monkeypatch.setattr(
        runner,
        "context",
        lambda *a: (
            {"ETHUSDT": {}},
            [("train", start, end)],
            [],
            end,
            {k: [] for k in ("splits", "folds", "settings", "matched_audit")},
            tmp_path,
            {},
        ),
    )
    monkeypatch.setattr(runner, "inventory", lambda *a: [])
    monkeypatch.setattr(runner, "prepare_case", lambda *a: None)
    calls = []

    def failed_baseline(_prepared, _case, variant, *args):
        calls.append(variant)
        raise ValueError("Baseline reproduction mismatch: synthetic injected regression")

    monkeypatch.setattr(runner, "run_case", failed_baseline)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/entry-timing-15m.md").write_text("test", encoding="utf-8")
    with pytest.raises(ValueError, match="Baseline reproduction mismatch"):
        runner.run(tmp_path)
    assert calls == ["baseline"]
    runs = list((tmp_path / "results/entry_timing_15m").iterdir())
    assert len(runs) == 1
    assert (runs[0] / "failure.json").exists()
    assert not (runs[0] / "timing").exists()
