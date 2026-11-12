"""Explicit tiny synthetic fixture generation; never download or use market history."""

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from quant_lab.history import HistoryRequest
from quant_lab.history_cache import save_bundle

from .execution_contracts import ExecutionPlan
from .execution_inputs import resolve_implementation
from .store import Store, database_path
from .workspaces import file_hash, write_json


def prepare_smoke(store, implementation_id, destination):
    attempt, request, _, _ = resolve_implementation(store, implementation_id)
    if (
        request.plan.operation != "NEW_STRATEGY"
        or request.hypothesis_manifest.data_requirements.timeframe != "1h"
    ):
        raise ValueError("This smoke fixture supports verified new single-timeframe1h strategies")
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    warmup = max(100, request.hypothesis_manifest.data_requirements.warmup_bars)
    if warmup > 1000:
        raise ValueError("Smoke warmup exceeds technical fixture limit1000")
    start = datetime(2000, 1, 10, tzinfo=UTC)
    history = HistoryRequest(start=start, end=start + timedelta(days=6), warmup_bars=warmup)
    index = pd.date_range(history.download_start, history.end, freq="h", inclusive="left")
    price = 100 + 0.02 * np.arange(len(index)) + np.sin(np.arange(len(index)) / 5)
    frame = pd.DataFrame(
        {
            "open": price + 0.05,
            "high": price + 0.3,
            "low": price - 0.3,
            "close": price,
            "volume": 10.0,
        },
        index=index,
    )
    provenance = destination / "synthetic-provenance.json"
    generator = destination / "generator-source.py"
    generator.write_bytes(Path(__file__).read_bytes())
    write_json(
        provenance,
        {
            "kind": "SYNTHETIC",
            "purpose": "TECHNICAL_ONLY",
            "generator": str(generator),
            "generator_sha256": file_hash(generator),
            "formula": "100 + .02*i + sin(i/5); deterministic; no random draws",
            "market_observations": False,
            "rows": len(frame),
            "request": history.model_dump(mode="json"),
        },
    )
    bundle = save_bundle(
        destination / "datasets",
        frame,
        history,
        [{"kind": "SYNTHETIC", "provenance_sha256": file_hash(provenance)}],
    )

    def period(offset):
        return {"start": start + timedelta(days=offset), "end": start + timedelta(days=offset + 2)}

    workspace = Path(attempt["workspace"])
    raw = {
        "schema_version": 1,
        "experiment_id": "orchestration_technical_smoke",
        "created_at": datetime.now(UTC),
        "description": "SYNTHETIC TECHNICAL ONLY; no economic conclusion or reserved holdout",
        "app": str(workspace / "configs/app.yaml"),
        "strategy": {"id": request.plan.target, "config": str(workspace / request.plan.paths()[1])},
        "markets": [
            {
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "dataset": str(bundle),
                "dataset_id": bundle.name,
                "warmup_bars": warmup,
            }
        ],
        "modes": ["LONG_ONLY"],
        "strategy_parameters": {},
        "execution": {
            "market_mode": "spot",
            "quantity_step": 0.000001,
            "min_quantity": 0.000001,
            "min_notional": 1.0,
            "filter_assumption": "Synthetic fixture; not historical exchange filters",
        },
        "validation": {"train": period(0), "validation": period(2), "test": period(4)},
    }
    experiment = destination / "experiment.yaml"
    with experiment.open("x", encoding="utf-8") as handle:
        yaml.safe_dump(raw, handle, sort_keys=False)
    plan = ExecutionPlan.model_validate(
        {
            "schema_version": "1.0",
            "experiment": str(experiment),
            "experiment_sha256": file_hash(experiment),
            "protocol": "StudyBackend v1 / lab_experiment_v1",
            "scope": "SYNTHETIC_TECHNICAL",
            "all_declared_periods_authorized": True,
            "review_note": "Technical smoke: three generated periods, no historical TEST",
            "enable_execution_copy": True,
            "datasets": [
                {
                    "path": str(bundle),
                    "dataset_id": bundle.name,
                    "manifest_sha256": file_hash(bundle / "manifest.json"),
                    "parquet_sha256": file_hash(bundle / "candles.parquet"),
                    "kind": "SYNTHETIC",
                    "provenance_note": "Generated formula and generator pinned; no market history",
                    "provenance_files": {
                        str(provenance): file_hash(provenance),
                        str(generator): file_hash(generator),
                    },
                }
            ],
            "max_wall_seconds": 120,
            "validation_timeout_seconds": 60,
            "max_backtests": 3,
            "max_candles": warmup + 144,
            "max_dataset_bytes": 1000000,
        }
    )
    write_json(destination / "execution-plan.json", plan.model_dump(mode="json"))
    return destination / "execution-plan.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("implementation_id")
    parser.add_argument("--db")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(prepare_smoke(Store(database_path(args.db)), args.implementation_id, args.output))
    return 0
