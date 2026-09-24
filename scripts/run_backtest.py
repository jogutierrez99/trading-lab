"""Run an implemented, enabled strategy against a verified local dataset. Offline."""

import argparse
import json
from pathlib import Path

from quant_lab.config import load_research_config, load_yaml
from quant_lab.execution_config import ExecutionConfig
from quant_lab.history import HistoryRequest
from quant_lab.history_cache import find_bundle, read_bundle
from quant_lab.research_run import result_document, run_strategy
from quant_lab.strategies.registry import StrategyRegistry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/history"))
    parser.add_argument("--dataset", type=Path, help="Select an explicit immutable dataset bundle")
    args = parser.parse_args()
    try:
        research = load_research_config(args.app)
        history = load_yaml(args.history, HistoryRequest)
        execution = load_yaml(args.execution, ExecutionConfig)
        registry = StrategyRegistry().discover()
        configured = next((s for s in research.strategies if s.name == args.strategy), None)
        if configured is None or not configured.enabled:
            raise ValueError(f"Strategy is missing or disabled: {args.strategy}")
        if args.strategy not in registry.names():
            raise ValueError(f"Strategy is not implemented: {args.strategy}")
        path = args.dataset or find_bundle(args.cache_dir, history)
        if path is None:
            raise ValueError("No validated cached dataset matches the historical request")
        candles = read_bundle(path, history)
        result = run_strategy(candles, history, research, args.strategy, execution, registry)
        print(
            json.dumps(
                result_document(result, candles, history, research, execution, args.strategy),
                default=str,
                allow_nan=False,
            )
        )
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, json.dumps({"event": "backtest_failed", "error": str(exc)}) + "\n")


if __name__ == "__main__":
    main()
