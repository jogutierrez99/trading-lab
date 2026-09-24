import pandas as pd
import pytest

from quant_lab.batch import Candidate, Window
from quant_lab.batch_002 import Batch002Plan, Fold
from quant_lab.batch_execution import BatchExecutor, bounded_view
from quant_lab.config import load_research_config, load_yaml
from quant_lab.execution_config import ExecutionConfig
from quant_lab.experiments import ExperimentStore
from quant_lab.history import HistoryRequest
from quant_lab.strategies.registry import StrategyRegistry


def test_rolling_folds_are_twelve_three_and_do_not_touch_holdout(repo_root):
    plan = load_yaml(repo_root / "configs/profiles/batch_002/batch.yaml", Batch002Plan)
    assert len(plan.candidates) == 12
    bad = plan.folds[0].model_dump()
    bad["train"]["start"] += pd.Timedelta(days=1)
    with pytest.raises(ValueError, match="12 calendar"):
        Fold.model_validate(bad)
    raw = plan.model_dump()
    raw["folds"][-1] = {
        "train": {
            "start": pd.Timestamp("2024-07-01T00:00Z").to_pydatetime(),
            "end": pd.Timestamp("2025-07-01T00:00Z").to_pydatetime(),
        },
        "test": plan.final_holdout.model_dump()
        | {"end": pd.Timestamp("2025-10-01T00:00Z").to_pydatetime()},
    }
    with pytest.raises(ValueError, match="final holdout"):
        Batch002Plan.model_validate(raw)


def test_long_history_view_is_bounded_and_real_executor_records(tmp_path, repo_root):
    import json

    import numpy as np

    index = pd.date_range("2023-01-01", "2025-03-03", inclusive="left", freq="h", tz="UTC")
    close = pd.Series(
        100 * np.exp(np.arange(len(index)) * 0.00001) + np.sin(np.arange(len(index)) * 0.1),
        index=index,
    )
    frame = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 10.0}
    )
    parent = HistoryRequest(
        start=index[768].to_pydatetime(),
        end=pd.Timestamp("2025-03-03T00:00Z").to_pydatetime(),
        warmup_bars=768,
    )
    window = Window(start=pd.Timestamp("2025-03-01T00:00Z").to_pydatetime(), end=parent.end)
    view, request = bounded_view(frame, parent, window, 768)
    assert len(view) == 816 and request.warmup_bars == 768
    assert view.index[-1] < window.end and len(frame) > 10000
    profile = repo_root / "configs/profiles/batch_002"
    research = load_research_config(profile / "app.yaml")
    execution = load_yaml(profile / "execution.yaml", ExecutionConfig)
    store = ExperimentStore(tmp_path, {"fixture": "synthetic"}, {})
    executor = BatchExecutor(store, research, execution, StrategyRegistry().discover())
    row = executor.execute(
        Candidate(id="test_vol", strategy="vol_momentum"), frame, parent, window, "test", "base"
    )
    result = json.loads((store.path / row["experiment_id"] / "result.json").read_text())
    assert result["metrics"]["observed_days"] == 2
    assert result["backend"] == "reference_v3"
    assert result["experiment"]["warmup_bars"] == 768
    assert result["metrics"]["closed_trades"] >= 1
    assert all(0.05 <= x <= 0.25 for x in result["entry_exposure_fraction"])
    assert result["metrics"]["ending_equity"] == pytest.approx(
        10000 + sum(t["net_pnl"] for t in result["trades"])
    )
