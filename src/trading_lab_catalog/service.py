"""Adapters for discovery and deterministic queries."""

import inspect
import subprocess
from pathlib import Path

from .models import Bundle, Strategy, Version, fingerprint


def discover(registry=None):
    # Only discovery imports trusted strategy modules. Core queries never do.
    if registry is None:
        from quant_lab.strategies.registry import StrategyRegistry

        registry = StrategyRegistry().discover()
    import hashlib

    root = Path(__file__).resolve().parents[2]
    git = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    commit = git.stdout.strip() if git.returncode == 0 else None
    strategies, versions = [], []
    for item in registry.catalogue():
        cls = registry.implementation(item["strategy_id"])
        code = hashlib.sha256(Path(inspect.getfile(cls)).read_bytes()).hexdigest()
        config = root / item["config"]
        config_hash = hashlib.sha256(config.read_bytes()).hexdigest() if config.is_file() else None
        strategies.append(
            Strategy(
                id=item["strategy_id"],
                name=item["strategy_id"],
                description=item["strategy_id"],
                source="quant_lab",
            )
        )
        contents = dict(
            strategy_id=item["strategy_id"],
            semantic_version=item["version"],
            implementation_reference=item["implementation"],
            git_commit=commit,
            code_sha256=code,
            configuration_sha256=config_hash,
            parameter_schema=cls.parameter_model.model_json_schema(),
            metadata={
                "discovered": True,
                "implementation_status": item["status"],
                "description": item["description"],
                "created_at": item["created_at"],
                "timeframes": list(item["timeframes"]),
                "modes": list(item["modes"]),
            },
        )
        versions.append(Version(id="version-" + fingerprint(contents), **contents))
    return Bundle(strategies=strategies, versions=versions)


def joined_cases(store, **filters):
    versions = {r["id"]: r for r in store.records("versions")}
    experiments = {r["id"]: r for r in store.records("experiments")}
    runs = {r["id"]: r for r in store.records("runs")}
    strategies = {r["id"]: r for r in store.records("strategies")}
    decisions = store.records("research_decisions")
    result = []
    for case in store.records("case_results"):
        run = runs[case["run_id"]]
        experiment = experiments[run["experiment_id"]]
        version = versions[experiment["version_id"]]
        strategy = strategies[version["strategy_id"]]
        row = {**strategy, **version, **experiment, **run, **case}
        row["strategy_id"] = strategy["id"]
        applicable = [
            d
            for d in decisions
            if d["strategy_id"] == strategy["id"]
            and d["version_id"] in (None, version["id"])
            and d["run_id"] in (None, run["id"])
        ]
        for category, key in (("RESEARCH", "research_state"), ("ECONOMIC", "verdict")):
            selected = sorted(
                (d for d in applicable if d["category"] == category),
                key=lambda d: (d["decided_at_utc"] or "", d["id"]),
            )
            row[key] = selected[-1]["verdict"] if selected else "UNKNOWN"
        if all(value is None or row.get(key) == value for key, value in filters.items()):
            result.append(row)
    return result
