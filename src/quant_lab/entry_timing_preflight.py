"""Technical checks, pinned datasets/artifacts and three baseline replays."""

import argparse
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from quant_lab.entry_timing_protocol import DEFAULT_CONFIG, context, load_protocol
from quant_lab.experiments import provenance, write_json
from quant_lab.new_mtf_preflight import CHECKS, environment, isolated_test_environment
from quant_lab.new_mtf_runner import read_json

RECEIPTS = Path("reports/entry_timing_15m/preflight")


def require_preflight(repo, code, protocol):
    paths = sorted((repo / RECEIPTS).glob("*.json"))
    if not paths:
        raise ValueError("Missing preflight: python scripts/preflight_entry_timing_15m.py")
    record = read_json(paths[-1])
    if (
        not record.get("passed")
        or record.get("technical_only")
        or not record.get("code_unchanged")
        or record.get("code_sha256") != code["code_sha256"]
        or record.get("environment") != environment(code)
        or record.get("config") != protocol.model_dump(mode="json")
        or set(record.get("checks", {})) != set(CHECKS)
        or any(v.get("exit_code") != 0 for v in record["checks"].values())
        or not record.get("datasets_and_artifacts_verified")
        or len(record.get("baseline_reproduction", [])) != 3
        or any(r.get("status") != "reproduced" for r in record["baseline_reproduction"])
    ):
        raise ValueError(
            "Failed, technical-only or stale preflight; rerun full dedicated preflight"
        )
    return {
        "receipt": str(paths[-1].relative_to(repo)),
        "code_sha256": code["code_sha256"],
        "baseline_reproduction": record["baseline_reproduction"],
    }


def preflight(repo, config=DEFAULT_CONFIG, technical_only=False):
    from quant_lab.entry_timing_runner import baseline_smoke

    before = provenance(repo)
    protocol = load_protocol(repo, config)
    env = isolated_test_environment()
    print("Pytest temporaries:", env["PYTEST_DEBUG_TEMPROOT"], flush=True)
    checks = {}
    for command in CHECKS:
        print("START", command, flush=True)
        result = subprocess.run(
            [sys.executable, "-m", *command.split()],
            cwd=repo,
            capture_output=True,
            text=True,
            env=env if command == "pytest -q" else None,
        )
        checks[command] = {"exit_code": result.returncode, "output": result.stdout + result.stderr}
        print(command, result.returncode, flush=True)
        if result.returncode:
            print(checks[command]["output"][-5000:], flush=True)
    passed = all(c["exit_code"] == 0 for c in checks.values())
    replay, verified, error = [], False, None
    if passed and not technical_only:
        try:
            print("VERIFY frozen datasets and baseline artifacts", flush=True)
            data, early, late, _boundary, _ref, child, references = context(repo, protocol, before)
            verified = True
            replay = baseline_smoke(data, early + late, child, references)
        except (OSError, ValueError, KeyError, AssertionError) as exc:
            error, passed = str(exc), False
            print("ERROR:", error, flush=True)
    unchanged = before["code_sha256"] == provenance(repo)["code_sha256"]
    record = {
        "code_sha256": before["code_sha256"],
        "environment": environment(before),
        "config": protocol.model_dump(mode="json"),
        "technical_only": technical_only,
        "checks": checks,
        "datasets_and_artifacts_verified": verified,
        "baseline_reproduction": replay,
        "error": error,
        "code_unchanged": unchanged,
        "pytest_temporary_root": env["PYTEST_DEBUG_TEMPROOT"],
        "passed": passed and unchanged,
    }
    folder = repo / RECEIPTS
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12] + ".json"
    )
    write_json(path, record)
    print(path, flush=True)
    if technical_only:
        print(
            "Technical checks only; this receipt cannot authorize historical execution.", flush=True
        )
    return record["passed"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--technical-only",
        action="store_true",
        help="No historical replays; cannot authorize runner",
    )
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[2]
    os.chdir(repo)
    try:
        return 0 if preflight(repo, args.config, args.technical_only) else 1
    except (OSError, ValueError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
