import hashlib
import sqlite3

import pandas as pd
import pytest

from quant_lab.batch import BatchPlan, Window, classify, select_candidate, window_view
from quant_lab.config import load_yaml
from quant_lab.experiments import ExperimentStore
from quant_lab.history import HistoryRequest


def test_selection_rejects_holdouts_and_uses_train_tiebreaks():
    row = {
        "partition": "train",
        "costs": "base",
        "closed_trades": 25,
        "return_pct": 3.0,
        "max_drawdown_pct": 5.0,
        "sharpe": 1.0,
        "turnover_initial_equity": 10.0,
        "candidate": "b",
    }
    assert select_candidate([row, row | {"candidate": "a"}], "base") == ("a", True)
    assert select_candidate([row | {"closed_trades": 1}], "base") == ("base", False)
    with pytest.raises(ValueError, match="train"):
        select_candidate([row | {"partition": "test", "sharpe": 1000}], "base")


def test_small_samples_keep_failure_flags():
    base = {
        "closed_trades": 3,
        "observed_days": 92,
        "sharpe": -1.0,
        "sortino": -1.0,
        "profit_factor": 0.5,
        "return_pct": -3.0,
        "max_drawdown_pct": 5.0,
    }
    result = classify(base, base | {"return_pct": 1.0})
    assert result["classification"] == "INSUFFICIENT_DATA"
    assert result["flags"]["failed_after_costs"]
    assert result["flags"]["failed_oos"]


def test_ledger_terminal_results_are_immutable(tmp_path):
    store = ExperimentStore(tmp_path, {"test": True}, {})
    experiment = store.start({"strategy": "test"})
    store.finish(experiment, {"metrics": {"net": 2.0}})
    with pytest.raises(ValueError, match="finalized"):
        store.finish(experiment, {"metrics": {"net": 999.0}})
    payload = (store.path / experiment / "result.json").read_bytes()
    with sqlite3.connect(store.path / "ledger.sqlite") as db:
        status, digest = db.execute("SELECT status, result_sha256 FROM experiments").fetchone()
    assert status == "completed" and digest == hashlib.sha256(payload).hexdigest()


def test_batch_plan_rejects_temporal_leakage(repo_root):
    plan = load_yaml(repo_root / "configs/profiles/batch_001/batch.yaml", BatchPlan)
    raw = plan.model_dump()
    raw["walk_forward"] = [plan.test.model_dump()]
    with pytest.raises(ValueError, match="final test"):
        BatchPlan.model_validate(raw)


def test_window_view_keeps_context_but_excludes_future():
    index = pd.date_range("2022-01-01", "2022-01-05", inclusive="left", freq="h", tz="UTC")
    candles = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0}, index=index
    )
    parent = HistoryRequest(
        start=index[0].to_pydatetime(),
        end=pd.Timestamp("2022-01-05T00:00Z").to_pydatetime(),
        warmup_bars=0,
    )
    window = Window(
        start=pd.Timestamp("2022-01-03T00:00Z").to_pydatetime(),
        end=pd.Timestamp("2022-01-04T00:00Z").to_pydatetime(),
    )
    frame, request = window_view(candles, parent, window)
    assert request.warmup_bars == 48 and len(frame) == 72
    assert frame.index[-1] < window.end
