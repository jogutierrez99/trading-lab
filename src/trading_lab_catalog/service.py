"""Adapters for discovery and deterministic queries."""

import inspect
import subprocess
from pathlib import Path

from .models import Bundle, Strategy, Version, fingerprint


def _clean_revision(root):
    def git(*args):
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return result.stdout.strip()

    try:
        commit = git("rev-parse", "HEAD")
        if git(
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            "src/quant_lab",
            "configs/strategies",
        ):
            raise ValueError("Discovery requires clean strategy code and configuration")
        return commit
    except subprocess.CalledProcessError as exc:
        raise ValueError("Discovery requires a Git checkout with a known revision") from exc


def discover(registry=None, *, root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    commit = _clean_revision(root)
    # Only discovery imports trusted strategy modules. Core queries never do.
    if registry is None:
        from quant_lab.strategies.registry import StrategyRegistry

        registry = StrategyRegistry().discover()
    import hashlib

    strategies, versions = [], []
    captured = {}
    for item in registry.catalogue():
        cls = registry.implementation(item["strategy_id"])
        path = Path(inspect.getfile(cls)).resolve()
        relative = path.relative_to(root.resolve()).as_posix()
        revision = subprocess.run(
            ["git", "-C", str(root), "cat-file", "blob", commit + ":" + relative],
            capture_output=True,
            timeout=10,
        )
        if revision.returncode:
            raise ValueError("Discovered implementation is not in the Git revision")
        committed = revision.stdout
        captured[path] = path.read_bytes()
        if captured[path].replace(b"\r\n", b"\n") != committed.replace(b"\r\n", b"\n"):
            raise ValueError("Discovered implementation differs from Git revision")
        code = hashlib.sha256(captured[path]).hexdigest()
        config = root / item["config"]
        if config.is_file():
            captured[config] = config.read_bytes()
            config_revision = subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "cat-file",
                    "blob",
                    commit + ":" + config.resolve().relative_to(root.resolve()).as_posix(),
                ],
                capture_output=True,
                timeout=10,
            )
            if config_revision.returncode:
                raise ValueError("Discovered configuration is not in the Git revision")
            if captured[config].replace(b"\r\n", b"\n") != config_revision.stdout.replace(
                b"\r\n", b"\n"
            ):
                raise ValueError("Discovered configuration differs from Git revision")
        config_hash = hashlib.sha256(captured[config]).hexdigest() if config.is_file() else None
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
                "git_provenance": "COMMITTED_VERIFIED",
                "discovered": True,
                "implementation_status": item["status"],
                "description": item["description"],
                "created_at": item["created_at"],
                "timeframes": list(item["timeframes"]),
                "modes": list(item["modes"]),
            },
        )
        versions.append(Version(id="version-" + fingerprint(contents), **contents))
    if _clean_revision(root) != commit or any(
        path.read_bytes() != raw for path, raw in captured.items()
    ):
        raise ValueError("Git identity or discovered bytes changed during discovery")
    return Bundle(strategies=strategies, versions=versions)


def joined_cases(store, **filters):
    versions = {r["id"]: r for r in store.records("versions")}
    experiments = {r["id"]: r for r in store.records("experiments")}
    runs = {r["id"]: r for r in store.records("runs", declarations=True)}
    strategies = {r["id"]: r for r in store.records("strategies")}
    decisions = store.records("research_decisions")
    accreditations = store.accreditations()
    result = []
    for case in store.records("case_results", declarations=True):
        run = runs[case["run_id"]]
        experiment = experiments[run["experiment_id"]]
        version = versions[experiment["version_id"]]
        strategy = strategies[version["strategy_id"]]
        row = {**strategy, **version, **experiment, **run, **case}
        row["strategy_id"] = strategy["id"]
        row["declared_run_audit_status"] = run["audit_status"]
        row["declared_case_audit_status"] = case["audit_status"]
        row["run_audit_status"] = (
            "SOURCE_AUDITED"
            if ("SOURCE_AUDITED_runs", fingerprint(run)) in accreditations
            else "UNVERIFIED"
        )
        row["case_audit_status"] = (
            "SOURCE_AUDITED"
            if ("SOURCE_AUDITED_case_results", fingerprint(case)) in accreditations
            else "UNVERIFIED"
        )
        row["audit_status"] = (
            "SOURCE_AUDITED"
            if row["run_audit_status"]
            == row["case_audit_status"]
            == run["audit_status"]
            == case["audit_status"]
            == "SOURCE_AUDITED"
            else "UNVERIFIED"
        )
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
