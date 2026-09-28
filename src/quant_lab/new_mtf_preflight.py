"""Immutable preflight receipts bound to source and runtime dependencies."""

import importlib.metadata
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from quant_lab.experiments import provenance, write_json

CHECKS = ("pytest -q", "ruff check .", "ruff format --check .", "pip check")


def isolated_test_environment():
    """Keep pytest and its child processes away from another Windows user's caches."""
    env = os.environ.copy()
    env["PYTEST_DEBUG_TEMPROOT"] = tempfile.mkdtemp(prefix="new-mtf-preflight-")
    env["PYTEST_ADDOPTS"] = (env.get("PYTEST_ADDOPTS", "") + " -p no:cacheprovider").strip()
    return env


def environment(code):
    return {
        "python": code["python"],
        "dependencies": code["dependencies"]
        | {name: importlib.metadata.version(name) for name in ("pytest", "ruff", "pip")},
    }


def preflight(repo: Path):
    before = provenance(repo)
    test_env = isolated_test_environment()
    print("Pytest temporaries:", test_env["PYTEST_DEBUG_TEMPROOT"], flush=True)
    checks = {}
    for command in CHECKS:
        print("START", command, flush=True)
        result = subprocess.run(
            [sys.executable, "-m", *command.split()],
            cwd=repo,
            capture_output=True,
            text=True,
            env=test_env if command == "pytest -q" else None,
        )
        checks[command] = {"exit_code": result.returncode, "output": result.stdout + result.stderr}
        print(command, result.returncode, flush=True)
        if result.returncode:
            print("\n".join(checks[command]["output"].splitlines()[-12:]), flush=True)
    after = provenance(repo)
    unchanged = before["code_sha256"] == after["code_sha256"]
    folder = repo / "reports/new_mtf_strategies/preflight"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12] + ".json"
    )
    record = {
        "code_sha256": before["code_sha256"],
        "environment": environment(before),
        "checks": checks,
        "pytest_temporary_root": test_env["PYTEST_DEBUG_TEMPROOT"],
        "pytest_addopts": test_env["PYTEST_ADDOPTS"],
        "code_unchanged": unchanged,
        "passed": unchanged and all(v["exit_code"] == 0 for v in checks.values()),
    }
    write_json(path, record)
    print(path, flush=True)
    return record["passed"]


def require_preflight(repo: Path, code: dict) -> dict:
    paths = sorted((repo / "reports/new_mtf_strategies/preflight").glob("*.json"))
    if not paths:
        raise ValueError("Missing preflight: run scripts/preflight_new_mtf_strategies.py")
    record = json.loads(paths[-1].read_text(encoding="utf-8"))
    if (
        not record.get("passed")
        or not record.get("code_unchanged")
        or record.get("code_sha256") != code["code_sha256"]
        or record.get("environment") != environment(code)
        or set(record.get("checks", {})) != set(CHECKS)
        or any(v.get("exit_code") != 0 for v in record["checks"].values())
    ):
        raise ValueError("Failed or stale preflight; rerun dedicated preflight")
    return record | {"receipt": str(paths[-1].relative_to(repo))}
