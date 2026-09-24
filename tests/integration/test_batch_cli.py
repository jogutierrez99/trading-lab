import json
import os
import shutil
import sqlite3
import subprocess
import sys

import numpy as np
import pandas as pd
import yaml

from quant_lab.config import load_yaml
from quant_lab.history import HistoryRequest
from quant_lab.history_cache import save_bundle


def test_offline_batch_and_individual_cli(tmp_path, repo_root):
    profile = tmp_path / "profile"
    shutil.copytree(repo_root / "configs/profiles/batch_001", profile)
    request = HistoryRequest(
        start=pd.Timestamp("2022-01-01T00:00Z").to_pydatetime(),
        end=pd.Timestamp("2022-02-15T00:00Z").to_pydatetime(),
    )
    index = pd.date_range(request.download_start, request.end, inclusive="left", freq="h", tz="UTC")
    close = pd.Series(
        100 + np.arange(len(index)) * 0.05 + np.sin(np.arange(len(index)) / 10), index=index
    )
    frame = pd.DataFrame(
        {"open": close, "high": close + 0.1, "low": close - 0.1, "close": close, "volume": 10.0}
    )
    bundle = save_bundle(tmp_path / "cache", frame, request, [{"kind": "synthetic_test_fixture"}])
    history_path = profile / "history.yaml"
    history_path.write_text(yaml.safe_dump(request.model_dump()), encoding="utf-8")
    assert load_yaml(history_path, HistoryRequest) == request
    plan = yaml.safe_load((profile / "batch.yaml").read_text())
    plan.update(
        history_file="history.yaml",
        dataset_dir=str(bundle),
        output_dir=str(tmp_path / "results"),
        walk_forward=[],
    )
    plan["candidates"] = [{"id": "trend_base", "strategy": "trend_following", "baseline": True}]
    for key, start, end in (
        ("train", "2022-01-10", "2022-01-20"),
        ("validation", "2022-01-20", "2022-02-01"),
        ("test", "2022-02-01", "2022-02-15"),
    ):
        plan[key] = {
            "start": pd.Timestamp(start, tz="UTC").to_pydatetime(),
            "end": pd.Timestamp(end, tz="UTC").to_pydatetime(),
        }
    config = profile / "batch.yaml"
    config.write_text(yaml.safe_dump(plan), encoding="utf-8")
    env = os.environ | {"PYTHONPATH": str(repo_root / "src")}
    run = subprocess.run(
        [sys.executable, str(repo_root / "scripts/run_batch.py"), "--config", str(config)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    (folder,) = (tmp_path / "results").iterdir()
    with sqlite3.connect(folder / "ledger.sqlite") as db:
        statuses = dict(db.execute("SELECT status, COUNT(*) FROM experiments GROUP BY status"))
    assert statuses == {"completed": 28, "skipped": 1}
    rows = pd.read_csv(folder / "metrics.csv")
    assert len(rows) == 28
    assert rows.query("partition == 'test'").observed_days.eq(14).all()
    assert (folder / "batch_001_summary.md").exists()
    command = [
        sys.executable,
        str(repo_root / "scripts/run_backtest.py"),
        "--app",
        str(profile / "app.yaml"),
        "--history",
        str(history_path),
        "--execution",
        str(profile / "execution.yaml"),
        "--strategy",
        "trend_following",
        "--dataset",
        str(bundle),
    ]
    single = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert single.returncode == 0, single.stderr
    document = json.loads(single.stdout)
    assert document["backend"] == "reference_v2"
    assert document["metrics"]["has_open_position"] is False
