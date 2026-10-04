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
    comparison = commands.add_parser("compare", help="Compare completed lab runs without backtests")
    comparison.add_argument("experiments", nargs="+")
    classification = commands.add_parser(
        "classify", help="Classify COMPLETE evidence without backtests"
    )
    classification.add_argument("identifier")
    classification.add_argument("--policy", type=Path)
    for name in ("publish", "publish-comparison"):
        publication = commands.add_parser(
            name, help="Write compact research_results; no Git operations"
        )
        publication.add_argument("identifier")
        publication.add_argument("--max-file-mb", type=float, default=5.0)
    challenge = commands.add_parser("challenge").add_subparsers(dest="action", required=True)
    for name in ("validate", "run"):
        action = challenge.add_parser(name)
        action.add_argument("identifier")
        if name == "validate":
            action.add_argument("--full", action="store_true")
    for name in ("validate", "run", "report"):
        command = commands.add_parser(name)
        command.add_argument("experiment")
        if name == "run":
            command.add_argument(
                "--resume",
                nargs="?",
                const="latest",
                help="Reuse verified results from latest or RUN_ID",
            )
            command.add_argument(
                "--check", action="store_true", help="Audit resume without backtests or writes"
            )
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
        elif args.command == "classify":
            from quant_lab.lab_classification import classify

            result = {"classification_directory": str(classify(root, args.identifier, args.policy))}
        elif args.command in {"publish", "publish-comparison"}:
            from quant_lab.lab_publish import publish, publish_comparison

            publish_command = publish if args.command == "publish" else publish_comparison
            result = publish_command(root, args.identifier, int(args.max_file_mb * 1_000_000))
        elif args.command == "challenge":
            from quant_lab.lab_challenge import prepare_challenge, resolve_challenge, run_challenge

            path, spec = resolve_challenge(root, args.identifier)
            if args.action == "validate":
                context = prepare_challenge(path, spec, full=args.full)
                result = {
                    "status": "VALID",
                    "validation": "FULL" if args.full else "FAST",
                    "experiment_id": spec.experiment_id,
                    "backtests": context["backtests"],
                    "candidates": context["candidates"],
                    "scope": "HISTORICAL_CHALLENGE; no backtests executed",
                }
            else:
                result = {"run_directory": str(run_challenge(path, spec, root))}
        elif args.command == "compare":
            from quant_lab.lab_comparison import compare

            result = {"comparison_directory": str(compare(root, args.experiments))}
        elif args.command == "report":
            result = locate(root, args.experiment)
            supplements = root / "reports/lab-classification" / result["run_id"]
            if result["status"] == "COMPLETE" and supplements.exists():
                from quant_lab.lab_classification import latest_classification
                from quant_lab.lab_evidence import completed_run

                found = latest_classification(root, completed_run(root, result["run_id"]))
                if found:
                    result["classification_json"] = str(found[0])
                    result["classification_summary"] = str(found[0].with_suffix(".md"))
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
                outcome = run(path, experiment, root, resume=args.resume, check_only=args.check)
                result = outcome if isinstance(outcome, dict) else {"run_directory": str(outcome)}
        print(json.dumps(result, indent=2, default=str, allow_nan=False))
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
