"""Small synthetic real-execution smoke; no historical workloads."""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from quant_lab.mtf_features import complete_bars
from quant_lab.mtf_series import run_batch
from quant_lab.new_mtf_reporting import report
from quant_lab.new_mtf_runner import matrix, run_phase


def test_new_family_real_runner_and_reports(tmp_path):
    price = 100 + np.arange(1000) * 0.01 + np.sin(np.arange(1000) / 8)
    f = pd.DataFrame(
        dict(open=price - 0.1, high=price + 0.4, low=price - 0.4, close=price, volume=1.0),
        index=pd.date_range("2020", periods=1000, freq="15min", tz="UTC"),
    )
    hourly = complete_bars(f, "15m", "1h")
    data = {
        "BTCUSDT": {
            "frames": {"1h": hourly},
            "mark": hourly,
            "quarter": f,
            "quarter_mark": f,
            "funding": pd.DataFrame({"rate": []}, index=pd.DatetimeIndex([], tz="UTC")),
        }
    }
    edges = [hourly.index[i] for i in (0, 100, 150, 200)] + [
        hourly.index[-1] + pd.Timedelta(hours=1)
    ]
    protocol = {
        "splits": [
            (name, str(a), str(b))
            for name, a, b in zip(
                ("train", "validation", "test", "final_holdout"), edges[:-1], edges[1:], strict=True
            )
        ],
        "folds": [[str(edges[0]), str(edges[1]), str(edges[2])]],
    }
    # Only 21 tiny synthetic executions, using the unmodified perpetual/MTF engine.
    path, _ = run_batch(
        tmp_path,
        "new_synthetic",
        data,
        matrix(("V4",), [("BTCUSDT", "keltner_breakout")]),
        protocol,
        {"code_sha256": "synthetic"},
    )
    classified = report(path, "b")
    assert not classified.research_pass.any()  # One synthetic fold cannot pass the 22-fold gate.
    assert json.loads((path / "verification.json").read_text())["executions"] == 21
    for name in (
        "research_pass.csv",
        "segment_metrics.csv",
        "fold_metrics.csv",
        "holdout.csv",
        "cost_sensitivity.csv",
        "trades.csv",
        "summary.md",
    ):
        assert (path / name).exists()


def test_no_survivors_skips_data_and_execution(tmp_path, monkeypatch):
    import quant_lab.new_mtf_runner as module

    monkeypatch.setattr(
        module,
        "phase_a_source",
        lambda *a: (
            tmp_path,
            pd.DataFrame(),
            {"eligible": [], "not_eligible": [], "reason": "none"},
        ),
    )
    monkeypatch.setattr(
        module, "matched_data", lambda *a: (_ for _ in ()).throw(AssertionError("data loaded"))
    )
    code = {"code_sha256": "synthetic", "files": {}}
    monkeypatch.setattr(module, "provenance", lambda *a: code)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/new-mtf-strategies.md").write_text("synthetic")
    reference = {"splits": [], "folds": [], "settings": {}, "matched_audit": {}}
    path = run_phase(tmp_path, "b", code, {}, reference, {}, {})
    assert json.loads((path / "verification.json").read_text())["v4_skipped"]
    assert json.loads((path / "verification.json").read_text())["configurations"] == 0
    assert (path / "artifact_manifest.json").exists()


def test_cli_help_lists_sequential_commands():
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, str(root / "scripts/run_new_mtf_strategies.py"), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "analyze" in completed.stdout and "--all" in completed.stdout
