"""Two deterministic UTC OHLCV fixtures; native cache/schema, never a second engine."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from quant_lab.history import HistoryRequest
from quant_lab.history_cache import save_bundle

from .circuit_contracts import ACCEPTANCE_TARGET, TARGET, technical_profile
from .execution_contracts import ExecutionPlan
from .execution_inputs import resolve_implementation
from .workspaces import file_hash, write_json


def check_pulse_signal_contract(strategy):
    """Independent cheap oracle, in the existing isolated native probe; no fills."""
    pair = strategy.name == ACCEPTANCE_TARGET
    if not pair and strategy.name != TARGET:
        raise ValueError("Technical pulse contract/strategy mismatch")
    for active, gap in ((True, False), (False, False), (True, True)):
        index = pd.date_range("2000-01-01", periods=48, freq="h", tz="UTC")
        if gap:
            split = 26 if pair else 25
            index = index[:split].append(index[split:] + pd.Timedelta(hours=1))
        close = np.full(48, 100.0)
        if active:
            close[np.isin(np.arange(48) % 8, [1, 2])] = 100.25
            close[np.arange(48) % 8 == 3] = 99.75
        frame = pd.DataFrame(
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": close, "volume": 10.0}, index=index
        )
        original = frame.copy(deep=True)
        signals = strategy.generate_signals(frame)
        entries = tuple(
            bool(
                i >= 20
                and i > 0
                and close[i] > 100
                and (
                    i > 1
                    and close[i - 1] > 100
                    and close[i - 2] <= 100
                    and index[i - 1] - index[i - 2] == pd.Timedelta(hours=1)
                    if pair
                    else close[i - 1] <= 100
                )
                and index[i] - index[i - 1] == pd.Timedelta(hours=1)
            )
            for i in range(48)
        )
        exits = tuple(
            bool(i >= 20 and (close[i] <= 100 if pair else close[i] < 100)) for i in range(48)
        )
        if (
            signals.long_entries != entries
            or signals.long_exits != exits
            or any(signals.short_entries)
            or any(signals.short_exits)
        ):
            raise ValueError(
                "Technical pulse signals contradict frozen entry/exit/warmup/gap rules"
            )
        prefix = strategy.generate_signals(frame.iloc[:33].copy())
        if prefix.long_entries != entries[:33] or prefix.long_exits != exits[:33]:
            raise ValueError("Technical pulse prefix invariance failed")
        pd.testing.assert_frame_equal(frame, original)
    return {
        "contract": "CANDLE_PAIR_V1" if pair else "CANDLE_PULSE_V1",
        "cases": 3,
        "rows_per_case": 48,
        "active_inactive_gap_warmup_prefix": "VERIFIED",
        "backtests": 0,
    }


def prepare_circuit_fixture(store, implementation_id, destination):
    attempt, request, _, _ = resolve_implementation(store, implementation_id)
    profile = technical_profile(request.hypothesis_manifest)
    if profile is None:
        raise ValueError("Fixture requires a frozen technical profile")
    target, fixture, experiment_id = profile
    if request.plan.target != target:
        raise ValueError("Fixture requires the exact verified technical implementation")
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    generator = destination / "generator.py"
    generator.write_bytes(Path(__file__).read_bytes())
    start = datetime(2000, 1, 20 if target == ACCEPTANCE_TARGET else 10, tzinfo=UTC)
    datasets, markets = [], []
    for symbol, active in (("BTC/USDT", True), ("ETH/USDT", False)):
        history = HistoryRequest(
            symbol=symbol, start=start, end=start + timedelta(days=6), warmup_bars=20
        )
        index = pd.date_range(history.download_start, history.end, freq="h", inclusive="left")
        phase = np.arange(len(index)) % 8
        close = np.full(len(index), 100.0)
        if active:
            close[np.isin(phase, [1, 2])] = 100.25
            close[phase == 3] = 99.75
        frame = pd.DataFrame(
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": close, "volume": 10.0}, index=index
        )
        provenance = destination / (symbol[:3] + "-provenance.json")
        write_json(
            provenance,
            {
                "kind": "SYNTHETIC",
                "market_observations": False,
                "fixture": fixture,
                "case": "SIGNALS_ENTRIES_EXITS" if active else "NO_OPERATIONS",
                "formula": "O=100,H=101,L=99,V=10; active C=100.25 at i%8 in1,2;"
                "99.75 at3;100 otherwise",
                "rows": len(frame),
                "request": history.model_dump(mode="json"),
                "generator_sha256": file_hash(generator),
            },
        )
        bundle = save_bundle(
            destination / "datasets",
            frame,
            history,
            [{"kind": "SYNTHETIC", "provenance_sha256": file_hash(provenance)}],
        )
        datasets.append(
            {
                "path": str(bundle),
                "dataset_id": bundle.name,
                "manifest_sha256": file_hash(bundle / "manifest.json"),
                "parquet_sha256": file_hash(bundle / "candles.parquet"),
                "kind": "SYNTHETIC",
                "provenance_note": "Deterministic technical pulse fixture; no market observations",
                "provenance_files": {
                    str(provenance): file_hash(provenance),
                    str(generator): file_hash(generator),
                },
            }
        )
        markets.append(
            {
                "symbol": symbol.replace("/", ""),
                "timeframe": "1h",
                "dataset": str(bundle),
                "dataset_id": bundle.name,
                "warmup_bars": 20,
            }
        )

    def period(offset):
        return {"start": start + timedelta(days=offset), "end": start + timedelta(days=offset + 2)}

    workspace = Path(attempt["workspace"])
    raw = {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "created_at": datetime.now(UTC),
        "description": "SYNTHETIC INTEGRATION ONLY; not economic evidence",
        "app": str(workspace / "configs/app.yaml"),
        "strategy": {"id": target, "config": str(workspace / request.plan.paths()[1])},
        "markets": markets,
        "modes": ["LONG_ONLY"],
        "strategy_parameters": {},
        "execution": {
            "market_mode": "spot",
            "quantity_step": 0.000001,
            "min_quantity": 0.000001,
            "min_notional": 1.0,
            "filter_assumption": "Synthetic fixture, not exchange provenance",
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
            "review_note": "Six technical cases: active BTC and inactive ETH; no reserved data",
            "enable_execution_copy": True,
            "datasets": datasets,
            "max_wall_seconds": 120,
            "validation_timeout_seconds": 60,
            "max_backtests": 6,
            "max_candles": 328,
            "max_dataset_bytes": 2000000,
        }
    )
    write_json(destination / "execution-plan.json", plan.model_dump(mode="json"))
    return plan


def verify_circuit_coverage(native):
    if not native["synthetic"] or native["summary"]["valid_backtests"] != 6:
        raise ValueError("Expected six completed synthetic technical cases")
    cases = native["native_results"]
    coverage = []
    for symbol, active in (("BTCUSDT", True), ("ETHUSDT", False)):
        selected = [x for x in cases if x["result"]["metrics"]["symbol"] == symbol]
        if len(selected) != 3 or {x["result"]["metrics"]["period"] for x in selected} != {
            "train",
            "validation",
            "test",
        }:
            raise ValueError("Synthetic coverage matrix is incomplete")
        for item in selected:
            metrics, trades = item["result"]["metrics"], item["result"]["trades"]
            if (active and not trades) or (not active and metrics["closed_trades"] != 0):
                raise ValueError(
                    "Missing signal/entry/exit or no-operation coverage; "
                    "no strategy optimization allowed"
                )
            coverage.append(
                {
                    "symbol": symbol,
                    "period": metrics["period"],
                    "closed_trades": metrics["closed_trades"],
                    "case": "ENTRIES_EXITS" if active else "NO_OPERATIONS",
                }
            )
    return coverage
