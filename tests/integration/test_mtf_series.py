"""Synthetic complete batch, immutable persistence and matched-cohort policy."""

import hashlib
import json

import pandas as pd
import pytest

from quant_lab.mtf_data import load_quarters
from quant_lab.mtf_features import complete_bars
from quant_lab.mtf_reporting import classify, finish_series
from quant_lab.mtf_series import run_batch


def quarter_frame(n=2000):
    import numpy as np

    index = pd.date_range("2020-01-01", periods=n, freq="15min", tz="UTC")
    price = 100 + np.arange(n) * 0.02 + np.sin(np.arange(n) / 10) * 2
    return pd.DataFrame(
        {"open": price, "high": price + 0.5, "low": price - 0.5, "close": price, "volume": 1.0},
        index=index,
    )


def test_full_synthetic_batch_and_reporting(tmp_path):
    f = quarter_frame()
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
    edges = [hourly.index[i] for i in (0, 250, 350, 425)] + [
        hourly.index[-1] + pd.Timedelta(hours=1)
    ]
    protocol = {
        "splits": [
            (n, str(a), str(b))
            for n, a, b in zip(
                ("train", "validation", "test", "final_holdout"), edges[:-1], edges[1:], strict=True
            )
        ],
        "folds": [[str(edges[0]), str(edges[1]), str(edges[2])]],
    }
    configs = [
        {
            "asset": "BTCUSDT",
            "family": "donchian",
            "architecture": v,
            "mode": "LONG_ONLY",
            "cohort": "matched",
        }
        for v in ("V1", "V3")
    ]
    path, comparison = run_batch(
        tmp_path, "synthetic", data, configs, protocol, {"code_sha256": "synthetic"}
    )
    assert json.loads((path / "verification.json").read_text())["executions"] == 42
    assert len(comparison) == 2
    assert (path / "trades.csv").exists()
    assert (path / "holdout_unlock.json").exists()
    destination = tmp_path / "evolution"
    destination.mkdir()
    finish_series(destination, [comparison], {"selected": []})
    assert (destination / "master_table.csv").exists()


def test_matched_exclusion_is_symmetric_and_original_untouched(tmp_path, monkeypatch):
    import quant_lab.mtf_data as module

    monkeypatch.setattr(module, "QUARTERS", tmp_path)
    f = quarter_frame(192)
    reference = complete_bars(f, "15m", "1h")
    data = {
        a: {
            "frames": {"1h": reference.copy()},
            "mark": reference.copy(),
            "funding": pd.DataFrame({"rate": [0.001, 0.002]}, index=reference.index[[0, 24]]),
        }
        for a in ("BTCUSDT", "ETHUSDT")
    }
    original = reference.copy()
    for a in data:
        for kind in ("klines", "markPriceKlines"):
            frame = f.copy()
            if a == "BTCUSDT" and kind == "markPriceKlines":
                frame.loc[frame.index[100], "high"] += 1
            root = tmp_path / a / kind
            root.mkdir(parents=True)
            frame.to_parquet(root / "data.parquet")
            (root / "manifest.json").write_text(
                json.dumps(
                    {"sha256": hashlib.sha256((root / "data.parquet").read_bytes()).hexdigest()}
                )
            )
    report = load_quarters(data, matched=True)
    assert len(report["excluded_days"]) == 1
    for item in data.values():
        assert len(item["frames"]["1h"]) == 24
        assert len(item["quarter"]) == len(item["quarter_mark"]) == 96
        assert len(item["funding"]) == 1
    pd.testing.assert_frame_equal(reference, original)


@pytest.mark.parametrize(
    "hold_trades,hold_return,promising", [(30, 1, True), (29, 1, False), (30, 0, False)]
)
def test_survivor_rules_are_not_relaxed(hold_trades, hold_return, promising):
    rows = []
    for partition in ("full", "train", "validation", "test", "final_holdout", "wf_00_test"):
        for costs in ("zero", "base", "adverse"):
            rows.append(
                {
                    "asset": "BTCUSDT",
                    "family": "donchian",
                    "architecture": "V1",
                    "mode": "LONG_ONLY",
                    "cohort": "matched",
                    "partition": partition,
                    "costs": costs,
                    "return_pct": hold_return if partition == "final_holdout" else 1,
                    "closed_trades": hold_trades if partition == "final_holdout" else 100,
                    "profit_factor": 1.1,
                    "sharpe": 0.2,
                }
            )
    result = classify(pd.DataFrame(rows))
    assert ("PROMISING_BUT_UNCONFIRMED" in result.classification.iloc[0]) == promising
