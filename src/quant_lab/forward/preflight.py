"""Explicit read-only checks. Technical-only never certifies account connectivity."""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from quant_lab.brokers.okx_demo import OKXDemoBroker, safety_environment
from quant_lab.experiments import provenance
from quant_lab.forward.config import load_config
from quant_lab.forward.feeds import history, instrument_lookup
from quant_lab.forward.runner import DEFAULT_CONFIG, ROOT
from quant_lab.market_data.okx import BARS, OKXMarketData


def connectivity(config_path, *, public_only=False, full_warmup=False):
    config, _inherited, _output = load_config(config_path)
    safety_environment()
    broker = OKXDemoBroker()
    clock = broker.server_time()
    instruments, warnings = instrument_lookup(config, broker)
    feed = OKXMarketData(broker, list(instruments))
    for instrument in instruments:
        for timeframe in BARS:
            _bars, warning = history(config, feed, instrument, timeframe, full=full_warmup)
            if warning:
                warnings.append(warning)
    snapshot = None if public_only else broker.reconcile()
    # Report counts only. Raw private state is never printed in terminals.
    return {
        "server_time_ms": clock,
        "instruments": {k: asdict(v) for k, v in instruments.items()},
        "market_data": "REST_OK",
        "warmup": "REQUIRED_FEEDS_VERIFIED" if full_warmup else "NOT_CHECKED",
        "required_feeds": [
            {"instrument": i, "timeframe": tf}
            for i in instruments
            for tf in BARS
            if config.required_feed(i, tf)
        ],
        "monitoring_warnings": warnings,
        "private_account": "not_checked" if public_only else "READ_ONLY_OK",
        "positions": len(snapshot["positions"]) if snapshot else None,
        "open_orders": len(snapshot["open_orders"]) if snapshot else None,
        "mutations": 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Forward preflight; no orders or historical batches"
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--technical-only", action="store_true")
    parser.add_argument("--public-only", action="store_true")
    args = parser.parse_args(argv)
    load_config(args.config)
    if importlib.util.find_spec("websockets") is None:
        parser.error('Install dependencies first: python -m pip install -e ".[dev,forward]"')
    before = provenance(ROOT)
    checks = []
    check_directory = create_check_directory(ROOT)
    print(f"Python: {sys.executable}", flush=True)
    print(f"Preflight logs: {check_directory}", flush=True)
    for index, command in enumerate(technical_commands(), start=1):
        run_check(command, ROOT, check_directory / f"{index:02d}-{command[2]}.log")
        checks.append(command)
    after = provenance(ROOT)
    if (before["code_sha256"], before["dependencies"]) != (
        after["code_sha256"],
        after["dependencies"],
    ):
        raise RuntimeError("Code or dependencies changed during preflight; rerun on a stable tree")
    connection = (
        None
        if args.technical_only
        else connectivity(args.config, public_only=args.public_only, full_warmup=True)
    )
    receipt = {
        "timestamp": datetime.now(UTC).isoformat(),
        "checks": checks,
        "check_directory": str(check_directory),
        "connectivity": connection,
        "mode": "technical_only"
        if args.technical_only
        else "public_only"
        if args.public_only
        else "read_only_demo",
        "demo_execution": "BLOCKED_NOT_IMPLEMENTED",
        "code_sha256": after["code_sha256"],
        "dependencies": after["dependencies"],
        "signal_parity_tests": "passed",
    }
    directory = ROOT / "reports/forward/preflight"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12] + ".json"
    )
    path.write_text(json.dumps(receipt, default=str, indent=2), encoding="utf-8")
    print(path)


def create_check_directory(root):
    directory = root / "reports/forward/preflight/checks" / uuid4().hex[:12]
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def technical_commands():
    # Keep temporary checkouts outside this repository: otherwise nested pytest
    # processes inherit this repo's pyproject/pythonpath instead of their checkout.
    # Reserve a unique parent, then give pytest a fresh child it can safely manage.
    temporary = Path(tempfile.mkdtemp(prefix="quant-forward-")) / "pytest"
    return (
        [sys.executable, "-m", "pytest", "-q", "--basetemp", str(temporary)],
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "ruff", "format", "--check", "."],
        [sys.executable, "-m", "pip", "check"],
    )


def run_check(command, root, log_path):
    environment = os.environ.copy()
    if command[1:3] == ["-m", "pytest"]:
        # Also inherited by the subprocess pytest used in scaffolding integration tests.
        environment["PYTEST_ADDOPTS"] = (
            environment.get("PYTEST_ADDOPTS", "") + " -p no:cacheprovider"
        )
    if command[1:3] == ["-m", "ruff"]:
        environment["RUFF_CACHE_DIR"] = str(log_path.parent / "ruff-cache")
    with log_path.open("w", encoding="utf-8") as log:
        with subprocess.Popen(
            command,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            env=environment,
        ) as process:
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(line)
            returncode = process.wait()
    if returncode:
        raise SystemExit(f"Preflight check failed (exit {returncode}). Full output: {log_path}")


def connection_main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only OKX EU demo connectivity")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--public-only", action="store_true")
    parser.add_argument(
        "--full-warmup",
        action="store_true",
        help="Check all configured warmup candles without rerunning software tests",
    )
    args = parser.parse_args(argv)
    print(
        json.dumps(
            connectivity(args.config, public_only=args.public_only, full_warmup=args.full_warmup),
            default=str,
            indent=2,
        )
    )
