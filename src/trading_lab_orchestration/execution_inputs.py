"""Verify implementation evidence and create an isolated, identified execution copy."""

import ast
import io
import json
import os
import stat
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

import yaml

from .implementation import Coordinator
from .process_identity import pending
from .workspaces import changes, file_hash, inventory, write_json


def relative_file(root: Path, name: str) -> Path:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
        raise ValueError("Non-relative artifact path")
    result = root / name
    if not result.resolve().is_relative_to(root.resolve()) or result.is_symlink():
        raise ValueError("Linked/escaping artifact path")
    return result


def verify_hashes(files: dict) -> None:
    for name, expected in files.items():
        if not Path(name).is_file() or file_hash(Path(name)) != expected:
            raise ValueError(f"Missing or changed pinned input: {name}")


def verified_implementation(store, identifier):
    coordinator = Coordinator(store)
    attempt = coordinator.attempt(identifier)
    state = store.show(attempt["task_id"])
    if (attempt["status"], state["task"]["status"], state["status"]) != (
        "SUCCEEDED",
        "SUCCEEDED",
        "IMPLEMENTATION_READY",
    ) or pending(attempt):
        raise ValueError("Implementation must be verified, ready and stopped")
    request = coordinator._request(attempt)
    prefix = "Verified receipt: "
    if not attempt["error"].startswith(prefix):
        raise ValueError("No coordinator-attested implementation receipt")
    receipt_path = Path(attempt["error"][len(prefix) :]).resolve()
    root = Path(attempt["root"]).resolve()
    if receipt_path.name != "receipt.json" or receipt_path.parent.parent != root:
        raise ValueError("Implementation receipt outside its evidence directory")
    hashes = json.loads((receipt_path.parent / "hashes.json").read_text())
    if hashes.get("receipt.json") != file_hash(receipt_path):
        raise ValueError("Implementation receipt hash mismatch")
    for name, sha in hashes.items():
        if file_hash(relative_file(receipt_path.parent, name)) != sha:
            raise ValueError("Implementation verification evidence changed")
    receipt = json.loads(receipt_path.read_text())
    if receipt["status"] != "IMPLEMENTED_VERIFIED":
        raise ValueError("Requires IMPLEMENTED_VERIFIED")
    for name in ("attempt_id", "task_id", "candidate_id", "base_commit", "hypothesis_sha256"):
        if receipt[name] != getattr(request, name):
            raise ValueError(f"Implementation receipt identity mismatch: {name}")
    if receipt["request_sha256"] != attempt["request_sha256"]:
        raise ValueError("Implementation receipt request mismatch")
    for name, sha in receipt["source_artifacts_sha256"].items():
        if file_hash(relative_file(root, name)) != sha:
            raise ValueError("Implementation source evidence changed")
    if len(receipt["checks"]) != len(request.authorized_checks) or any(
        c["exit_code"] or c["timed_out"] or c["authorized_argv"] != command
        for c, command in zip(receipt["checks"], request.authorized_checks, strict=True)
    ):
        raise ValueError("Implementation checks do not support success")
    final = changes(attempt)
    if final != receipt["files"] or set(final) != set(request.allowed_write_paths):
        raise ValueError("Implementation files changed after verification")
    delivered = {item["path"]: item["sha256"] for item in receipt["model_delivery"]["files"]}
    repair = receipt.get("operator_format_repair")
    if repair:
        if repair["before"] != delivered or repair["after"] != final or not repair["ast_unchanged"]:
            raise ValueError("Final identity omits or contradicts the format repair")
        archive = Path(repair["evidence"]).resolve()
        if archive.parent != root:
            raise ValueError("Format repair archive outside implementation")
        for name, sha in delivered.items():
            original = relative_file(archive / "before", name)
            current = relative_file(Path(attempt["workspace"]), name)
            if file_hash(original) != sha:
                raise ValueError("Original format repair bytes changed")
            if name.endswith(".py"):
                if ast.dump(ast.parse(original.read_bytes())) != ast.dump(
                    ast.parse(current.read_bytes())
                ):
                    raise ValueError("Format repair changed AST")
            elif file_hash(current) != sha:
                raise ValueError("Non-Python format repair change")
    elif delivered != final:
        raise ValueError("Final files contradict model delivery without an identified repair")
    return attempt, request, receipt_path, receipt


def resolve_implementation(store, identifier):
    if identifier.startswith("repair_"):
        from .manual_repair import ManualRepair

        return ManualRepair(store).verified(identifier)
    return verified_implementation(store, identifier)


def archive_base(attempt, destination):
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=" + os.devnull,
            "-c",
            "core.fsmonitor=false",
            "-C",
            attempt["repo"],
            "archive",
            "--format=zip",
            attempt["base_commit"],
        ],
        capture_output=True,
        timeout=30,
        shell=False,
    )
    if result.returncode:
        raise ValueError("Cannot archive immutable implementation base")
    destination.mkdir(exist_ok=False)
    with zipfile.ZipFile(io.BytesIO(result.stdout)) as archive:
        for member in archive.infolist():
            relative_file(destination, member.filename)
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError("Linked repository entries are not allowed")
        archive.extractall(destination)
    for name, sha in json.loads((Path(attempt["root"]) / "baseline.json").read_text()).items():
        if name == ".git":
            continue  # Never copy the worktree pointer or grant access to shared Git metadata.
        if file_hash(relative_file(destination, name)) != sha:
            raise ValueError("Archived base differs from verified implementation baseline")


def prepare_inputs(root, attempt, implementation, receipt, plan):
    from quant_lab.config import _read_mapping, load_yaml
    from quant_lab.lab_schema import Experiment

    source = Path(plan.experiment).resolve()
    if file_hash(source) != plan.experiment_sha256:
        raise ValueError("Experiment YAML hash mismatch")
    experiment = load_yaml(source, Experiment)
    if experiment.combinations != 1:
        raise ValueError("Step4.3 executes one fixed parameter configuration, not a sweep")
    if experiment.execution.market_mode not in {"spot", "synthetic"}:
        raise ValueError(
            "Only ordinary OHLCV runner is supported; use dedicated protocols separately"
        )
    if implementation.plan.operation == "NEW_EXPERIMENT":
        if source != (Path(attempt["workspace"]) / implementation.plan.paths()[0]).resolve():
            raise ValueError("Use the verified experiment implementation")
    elif experiment.strategy.id != implementation.plan.target:
        raise ValueError("Experiment strategy does not match the verified implementation")
    original_profile = (source.parent / experiment.strategy.config).resolve()
    if (
        implementation.plan.operation == "NEW_STRATEGY"
        and original_profile
        != (Path(attempt["workspace"]) / implementation.plan.paths()[1]).resolve()
    ):
        raise ValueError("Use the strategy profile in the verified delivery")
    original_app = (source.parent / experiment.app).resolve()
    app = _read_mapping(original_app)
    risk = (original_app.parent / app.get("risk_file", "risk.yaml")).resolve()
    for path in (original_profile, original_app, risk):
        if not path.is_relative_to(Path(attempt["workspace"]).resolve()):
            raise ValueError(
                "App, risk and profile must come from the verified implementation tree"
            )
    pins = {str(Path(pin.path).resolve()): pin for pin in plan.datasets}
    if len(pins) != len(plan.datasets) or set(pins) != {
        str((source.parent / m.dataset).resolve()) for m in experiment.markets
    }:
        raise ValueError("Pin every experiment dataset exactly once")
    if plan.scope == "SYNTHETIC_TECHNICAL" and any(p.kind != "SYNTHETIC" for p in pins.values()):
        raise ValueError("Technical acceptance cannot consume historical TEST/holdouts")
    inputs = {str(p): file_hash(p) for p in (source, original_profile, original_app, risk)}
    total_bytes = 0
    for pin in pins.values():
        pinned = {
            str(Path(pin.path) / "manifest.json"): pin.manifest_sha256,
            str(Path(pin.path) / "candles.parquet"): pin.parquet_sha256,
        } | pin.provenance_files
        for name, sha in pinned.items():
            if not Path(name).is_absolute():
                raise ValueError("Provenance paths must be absolute")
            total_bytes += Path(name).stat().st_size
            if total_bytes > plan.max_dataset_bytes:
                raise ValueError("Pinned dataset/provenance byte volume exceeds limit")
            if file_hash(Path(name)) != sha:
                raise ValueError(f"Dataset/provenance hash mismatch: {name}")
            inputs[str(Path(name).resolve())] = sha
    workspace = root / "workspace"
    archive_base(attempt, workspace)
    for name, sha in receipt["files"].items():
        content = relative_file(Path(attempt["workspace"]), name).read_bytes()
        path = relative_file(workspace, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(content)
        if file_hash(path) != sha:
            raise ValueError("Implementation overlay hash mismatch")
    config = workspace / "execution-config"
    config.mkdir(exist_ok=False)
    profile = _read_mapping(original_profile)
    before_enabled = profile.get("enabled", False)
    if not before_enabled and not plan.enable_execution_copy:
        raise ValueError("Profile disabled; explicitly authorize enabling only the execution copy")
    profile["enabled"] = True
    raw = experiment.model_dump()
    raw["app"] = "app.yaml"
    raw["strategy"]["config"] = "strategy.yaml"
    for market in raw["markets"]:
        pin = pins[str((source.parent / market["dataset"]).resolve())]
        market["dataset"] = str(Path(pin.path).resolve())
        market["dataset_id"] = pin.dataset_id
        if market["dataset_format"] != "bundle" or market["perpetual_data"] is not None:
            raise ValueError("Only pinned ordinary bundle datasets are supported in4.3")
    app["risk_file"] = "risk.yaml"
    for name, value in (
        ("experiment.yaml", raw),
        ("app.yaml", app),
        ("strategy.yaml", profile),
        ("risk.yaml", _read_mapping(risk)),
    ):
        with (config / name).open("x", encoding="utf-8") as handle:
            yaml.safe_dump(value, handle, sort_keys=False)
    write_json(
        root / "adaptations.json",
        {
            "source_experiment": str(source),
            "source_experiment_sha256": plan.experiment_sha256,
            "source_profile": str(original_profile),
            "source_profile_sha256": file_hash(original_profile),
            "enabled": {"before": before_enabled, "execution_copy": True},
            "experiment_changes": "Rebase app/profile/dataset paths; pin dataset_id only",
            "source_configuration_changed": False,
        },
    )
    write_json(root / "implementation-receipt.json", receipt)
    return inputs, inventory(workspace)
