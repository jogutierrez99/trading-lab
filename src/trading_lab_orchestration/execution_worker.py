"""Thin subprocess bridge: native FULL validator and native run, no second engine."""

import argparse
import json
import sys
import traceback
from pathlib import Path

from .execution_contracts import ExecutionRequest
from .execution_inputs import verify_hashes
from .native_interface import check_signal_interface, implementation_interface
from .workspaces import file_hash, inventory, write_json


def preflight(request):
    import pyarrow.parquet as pq

    comparison = request.plan.comparison
    # The parent already verified full source hashes. The scoped worker sees only slices.
    verify_hashes(
        request.runtime_files if comparison else request.input_files | request.runtime_files
    )
    root = Path(request.workspace)
    sealed = json.loads((root.parent / "workspace-files.json").read_text())
    if inventory(root) != sealed:
        raise ValueError("Execution workspace changed after preparation")
    sys.path.insert(0, str(root / "src"))
    import quant_lab
    from quant_lab.config import load_yaml
    from quant_lab.lab_runner import prepare
    from quant_lab.lab_schema import Experiment

    if not Path(quant_lab.__file__).resolve().is_relative_to(root):
        raise ValueError("Runner import escaped the frozen execution tree")
    experiment_path = Path(request.experiment)
    experiment = load_yaml(experiment_path, Experiment)
    if experiment.combinations != 1 or experiment.execution.market_mode not in {
        "spot",
        "synthetic",
    }:
        raise ValueError("Ordinary fixed-parameter OHLCV execution only")
    pins = {str(Path(p.path).resolve()): p for p in request.plan.datasets}
    candles = 0
    for market in experiment.markets:
        dataset = Path(market.dataset).resolve()
        if comparison:
            if not dataset.is_relative_to(root / "data") or dataset.name != market.dataset_id:
                raise ValueError("RMM runner can only read sealed TRAIN/VALIDATION slices")
        elif (
            market.dataset_format != "bundle" or pins[str(dataset)].dataset_id != market.dataset_id
        ):
            raise ValueError("Dataset format/identity contradicts request")
        candles += pq.ParquetFile(dataset / "candles.parquet").metadata.num_rows
    if candles > request.plan.max_candles:
        raise ValueError("Dataset candle volume exceeds request limit")
    # FAST counts and validates capabilities before loading all data or executing signals.
    options = {"period_names": comparison.periods} if comparison else {}
    context = prepare(experiment_path, experiment, full=False, **options)
    if context["backtests"] > request.plan.max_backtests:
        raise ValueError("Native backtest count exceeds request limit")
    context = prepare(experiment_path, experiment, full=True, **options)
    if sum(map(len, context["frames"])) != candles:
        raise ValueError("Loaded candle volume differs from metadata")
    for market, frame in zip(experiment.markets, context["frames"], strict=True):
        check_signal_interface(
            context["registry"],
            context["template"],
            context["parameters"][0],
            market,
            frame,
            experiment.validation.train,
        )
    report = {
        "status": "VALID",
        "validation": "FULL",
        "backtests": context["backtests"],
        "candles": candles,
        "datasets": context["datasets"],
        "periods": list(comparison.periods)
        if comparison
        else [name for name, _ in experiment.periods()],
        "signal_interface": "VALIDATED_TRAIN_PREFIX_ONLY",
    }
    if comparison:
        from .rmm_comparison import verify_parity

        baseline_path = experiment_path.with_name("baseline.yaml")
        baseline = load_yaml(baseline_path, Experiment)
        baseline_context = prepare(baseline_path, baseline, full=True, **options)
        verify_parity((baseline, experiment), (baseline_context, context))
        report["baseline_backtests"] = baseline_context["backtests"]
        report["total_backtests"] = context["backtests"] + baseline_context["backtests"]
    return experiment, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["validate", "run", "implementation-interface"])
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "implementation-interface":
            from .implementation_contracts import ImplementationRequest

            report = implementation_interface(
                ImplementationRequest.model_validate_json(args.request.read_text())
            )
            write_json(args.result, report)
            return 0
        request = ExecutionRequest.model_validate_json(args.request.read_text())
        experiment, report = preflight(request)
        if args.action == "run":
            from quant_lab.lab_runner import run

            comparison = request.plan.comparison
            options = {"period_names": comparison.periods} if comparison else {}
            if comparison:
                from quant_lab.config import load_yaml
                from quant_lab.lab_schema import Experiment

                baseline_path = Path(request.experiment).with_name("baseline.yaml")
                baseline_run = run(
                    baseline_path,
                    load_yaml(baseline_path, Experiment),
                    Path(request.workspace),
                    output=Path(request.results).parent / "comparison-baseline",
                    **options,
                )
                report["baseline_run_directory"] = str(baseline_run)
            directory = run(
                Path(request.experiment),
                experiment,
                Path(request.workspace),
                output=Path(request.results),
                **options,
            )
            outcome = json.loads((directory / "outcome.json").read_text())
            report |= {
                "run_directory": str(directory),
                "run_id": directory.name,
                "runner_status": outcome["status"],
                "outcome": outcome,
            }
        write_json(args.result, report)
        print(json.dumps({"result": str(args.result), "sha256": file_hash(args.result)}))
        return 0
    except Exception as exc:  # Process boundary: preserve unexpected native errors, never success.
        write_json(
            args.result, {"status": "FAILED", "error_type": type(exc).__name__, "error": str(exc)}
        )
        traceback.print_exc(file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
