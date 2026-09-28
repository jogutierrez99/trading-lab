"""Technical checks plus read-only config, source and matched-data verification."""

import argparse
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from quant_lab.experiments import provenance, write_json
from quant_lab.new_mtf_preflight import CHECKS, environment, isolated_test_environment
from quant_lab.new_mtf_runner import read_json
from quant_lab.optional_fill_protocol import DEFAULT_CONFIG, context, load_protocol

RECEIPTS = Path("reports/optional_15m_fill/preflight")


def require_preflight(repo, code, protocol):
    paths = sorted((repo / RECEIPTS).glob("*.json"))
    if not paths:
        raise ValueError("Run python scripts/preflight_optional_15m_fill.py first")
    record = read_json(paths[-1])
    if (
        not record.get("passed")
        or not record.get("code_unchanged")
        or record.get("code_sha256") != code["code_sha256"]
        or record.get("environment") != environment(code)
        or record.get("config") != protocol.model_dump(mode="json")
        or not record.get("datasets_and_artifacts_verified")
        or set(record.get("checks", {})) != set(CHECKS)
        or any(c.get("exit_code") != 0 for c in record["checks"].values())
    ):
        raise ValueError("Failed, technical-only or stale preflight; rerun dedicated preflight")
    return {"receipt": str(paths[-1].relative_to(repo)), "code_sha256": code["code_sha256"]}


def preflight(repo, config=DEFAULT_CONFIG, technical_only=False):
    before = provenance(repo)
    protocol = load_protocol(repo, config)
    env = isolated_test_environment()
    print("Pytest temporaries:", env["PYTEST_DEBUG_TEMPROOT"], flush=True)
    checks = {}
    for command in CHECKS:
        print("START", command, flush=True)
        process = subprocess.run(
            [sys.executable, "-m", *command.split()],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="backslashreplace",
            env=env if command == "pytest -q" else None,
        )
        checks[command] = {
            "exit_code": process.returncode,
            "output": process.stdout + process.stderr,
        }
        print(command, process.returncode, flush=True)
        if process.returncode:
            console_encoding = sys.stdout.encoding or "utf-8"
            printable = (
                checks[command]["output"][-5000:]
                .encode(console_encoding, errors="backslashreplace")
                .decode(console_encoding)
            )
            print(printable, flush=True)
    passed = all(c["exit_code"] == 0 for c in checks.values())
    verified, error, inventory = False, None, None
    if passed and not technical_only:
        try:
            print("VERIFY frozen artifacts and matched 15m data (no backtests)", flush=True)
            data, early, late, _b, _ref, _sources, references = context(repo, protocol)
            inventory = {
                "windows": len(early + late),
                "baseline_references": sum(map(len, references.values())),
                "quarter_bars": {asset: len(item["quarter"]) for asset, item in data.items()},
            }
            verified = True
        except (OSError, ValueError, KeyError, AssertionError) as exc:
            passed, error = False, str(exc)
            print("ERROR:", error, flush=True)
    unchanged = before["code_sha256"] == provenance(repo)["code_sha256"]
    record = {
        "code_sha256": before["code_sha256"],
        "environment": environment(before),
        "checks": checks,
        "config": protocol.model_dump(mode="json"),
        "code_unchanged": unchanged,
        "datasets_and_artifacts_verified": verified,
        "inventory": inventory,
        "technical_only": technical_only,
        "error": error,
        "passed": passed and unchanged,
        "pytest_temporary_root": env["PYTEST_DEBUG_TEMPROOT"],
    }
    folder = repo / RECEIPTS
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12] + ".json"
    )
    write_json(path, record)
    print(path, flush=True)
    if technical_only:
        print("Technical-only receipt cannot authorize the runner.", flush=True)
    return record["passed"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--technical-only", action="store_true")
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[2]
    os.chdir(repo)
    try:
        return 0 if preflight(repo, args.config, args.technical_only) else 1
    except (OSError, ValueError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
