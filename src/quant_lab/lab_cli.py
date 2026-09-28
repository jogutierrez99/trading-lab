"""Thin local CLI for discoverable strategies and YAML experiments."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from quant_lab.lab_reporting import locate, runs
from quant_lab.lab_runner import prepare, run
from quant_lab.lab_schema import discover, resolve
from quant_lab.strategies.registry import StrategyRegistry


def create(directory: Path, source: str, name: str) -> Path:
    """Clone a known valid definition, preserving concrete data/execution assumptions."""
    from quant_lab.lab_schema import Experiment

    _, original = resolve(directory, source)
    value = original.model_dump() | {"experiment_id": name, "created_at": datetime.now(UTC)}
    experiment = Experiment.model_validate(value)
    if name in discover(directory):
        raise ValueError(f"Duplicate experiment_id: {name}")
    path = directory / f"{name}.yaml"
    with path.open("x", encoding="utf-8") as handle:
        yaml.safe_dump(experiment.model_dump(), handle, sort_keys=False)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("strategies", "experiments", "status"):
        commands.add_parser(name)
    for name in ("validate", "run", "report"):
        command = commands.add_parser(name)
        command.add_argument("experiment")
        if name == "validate":
            command.add_argument(
                "--full", action="store_true", help="Verify all dataset bytes/OHLCV"
            )
    generator = commands.add_parser("experiment").add_subparsers(dest="action", required=True)
    creator = generator.add_parser("create")
    creator.add_argument("experiment_id")
    creator.add_argument("--from", dest="source", default="latest-experiment")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    directory = root / "configs/experiments"
    try:
        if args.command == "strategies":
            result = StrategyRegistry().discover().catalogue()
        elif args.command == "experiments":
            result = [
                {
                    "experiment_id": name,
                    "created_at": exp.created_at,
                    "strategy": exp.strategy.id,
                    "path": str(path),
                }
                for name, (path, exp) in discover(directory).items()
            ]
        elif args.command == "status":
            catalogue = StrategyRegistry().discover().catalogue()
            dated = [s for s in catalogue if s["created_at"] is not None]
            latest = (
                max(
                    dated, key=lambda s: (datetime.fromisoformat(s["created_at"]), s["strategy_id"])
                )
                if dated
                else None
            )
            experiments = discover(directory)
            history = runs(root)
            result = {
                "strategies": len(catalogue),
                "experiments": len(experiments),
                "latest_strategy": latest,
                "legacy_strategy_dates": "unknown; never inferred from mtime",
                "latest_experiment": resolve(directory, "latest-experiment")[1].experiment_id
                if experiments
                else None,
                "latest_run": history[-1] if history else None,
            }
            if history:
                result["latest_run"] = locate(root, "latest")
                summary = Path(history[-1]["path"]) / "summary.json"
                if summary.exists():
                    result["counts"] = json.loads(summary.read_text(encoding="utf-8"))
        elif args.command == "report":
            result = locate(root, args.experiment)
        elif args.command == "experiment":
            result = {
                "created": str(create(directory, args.source, args.experiment_id)),
                "next": "Edit YAML, then validate before run",
            }
        else:
            path, experiment = resolve(directory, args.experiment)
            if args.command == "validate":
                context = prepare(path, experiment, full=args.full)
                result = {
                    "status": "VALID",
                    "validation": "FULL" if args.full else "FAST",
                    "experiment_id": experiment.experiment_id,
                    "backtests": context["backtests"],
                    "note": "No backtests executed; run always performs full data preflight",
                }
            else:
                result = {"run_directory": str(run(path, experiment, root))}
        print(json.dumps(result, indent=2, default=str, allow_nan=False))
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
