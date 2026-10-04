"""Read-only compact evidence access shared by classification and publication."""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def new_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12]


def portable(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def completed_run(root: Path, identifier: str) -> dict:
    matches = []
    for file in (root / "results").glob("*/*/run.json"):
        header = read_json(file)
        if header.get("kind") not in {"lab_experiment_v1", "lab_challenge_v1"}:
            continue
        if identifier in {header["experiment_id"], header["run_id"]}:
            matches.append((header["created_at"], header["run_id"], file.parent, header))
    if not matches:
        raise ValueError(f"No lab run found: {identifier}")
    _, _, path, header = max(matches)
    if (
        not re.fullmatch(r"[a-z][a-z0-9_]*", header["experiment_id"])
        or not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[a-f0-9]{12}", header["run_id"])
        or path.name != header["run_id"]
        or path.parent.name != header["experiment_id"]
    ):
        raise ValueError("Run identity/path mismatch")
    outcome = read_json(path / "outcome.json")
    if outcome.get("status") != "COMPLETE":
        raise ValueError(f"Latest requested run is not COMPLETE: {path.name}")
    names = (
        "run.json",
        "outcome.json",
        "plan.json",
        "resolved.json",
        "provenance.json",
        "metrics.csv",
    )
    hashes = {name: sha256(path / name) for name in names}
    metrics = pd.read_csv(path / "metrics.csv")
    required = {
        "configuration_id",
        "backtest_id",
        "period",
        "scenario",
        "status",
        "symbol",
        "timeframe",
        "mode",
        "start",
        "end",
    }
    if not required <= set(metrics.columns):
        raise ValueError("Missing evidence identity columns")
    if len(metrics) != header["expected_backtests"] or outcome.get("backtests") != len(metrics):
        raise ValueError("Incomplete metrics count")
    if not metrics.status.eq("completed").all():
        raise ValueError("COMPLETE run contains non-completed backtests")
    if metrics.backtest_id.isna().any() or metrics.backtest_id.duplicated().any():
        raise ValueError("Missing or duplicate backtest identity")
    if metrics.duplicated(["configuration_id", "period", "scenario"]).any():
        raise ValueError("Duplicate evidence cell")
    result = {
        "path": path,
        "header": header,
        "outcome": outcome,
        "metrics": metrics,
        "plan": read_json(path / "plan.json"),
        "resolved": read_json(path / "resolved.json"),
        "provenance": read_json(path / "provenance.json"),
        "source_sha256": hashes,
    }
    if result["plan"]["experiment_id"] != header["experiment_id"]:
        raise ValueError("Plan/run identity mismatch")
    assert_unchanged(result)
    return result


def assert_unchanged(evidence: dict) -> None:
    if any(
        sha256(evidence["path"] / name) != value
        for name, value in evidence["source_sha256"].items()
    ):
        raise ValueError("Source evidence changed while being read")


def recorded_data_valid(evidence: dict) -> bool:
    """Check frozen provenance/coverage, not a new audit of dataset or equity bytes."""
    datasets = evidence["resolved"].get("datasets", [])
    markets = evidence["plan"].get("markets", [])
    if not datasets or len(markets) != len(datasets):
        return False
    for market, dataset in zip(markets, datasets, strict=True):
        manifest = dataset.get("manifest", {})
        audit = manifest.get("audit", {})
        recorded_valid = audit.get("status") == "VALID" or (
            "request" in manifest
            and manifest.get("dataset_id") == dataset.get("dataset_id")
            and manifest.get("parquet_sha256") == dataset.get("parquet_sha256")
        )
        if not recorded_valid or not dataset.get("dataset_id") or not dataset.get("parquet_sha256"):
            return False
        if (market["symbol"], market["timeframe"]) != (dataset["symbol"], dataset["timeframe"]):
            return False
        rows = evidence["metrics"]
        rows = rows[(rows.symbol == market["symbol"]) & (rows.timeframe == market["timeframe"])]
        if rows.empty:
            return False
        step = (
            pd.Timedelta(minutes=15)
            if market["timeframe"] == "15m"
            else pd.Timedelta(market["timeframe"])
        )
        if pd.to_datetime(rows.start, utc=True).min() - market["warmup_bars"] * step < pd.Timestamp(
            dataset["start"]
        ):
            return False
        if pd.to_datetime(rows.end, utc=True).max() > pd.Timestamp(dataset["end"]):
            return False
    return True
