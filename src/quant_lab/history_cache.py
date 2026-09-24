"""Immutable content-addressed Parquet bundles, verified on reuse."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

import pandas as pd

from quant_lab.candles import validate_candles
from quant_lab.history import HistoryRequest


def fingerprint(frame: pd.DataFrame, request: HistoryRequest) -> str:
    digest = hashlib.sha256(request.model_dump_json().encode())
    digest.update(frame.index.as_unit("ns").asi8.astype("<i8").tobytes())
    digest.update(frame.to_numpy(dtype="<f8").tobytes())
    return digest.hexdigest()


def read_bundle(path: Path, request: HistoryRequest) -> pd.DataFrame:
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    parquet = path / "candles.parquet"
    if manifest["request"] != request.model_dump(mode="json"):
        raise ValueError("Cache request mismatch")
    if hashlib.sha256(parquet.read_bytes()).hexdigest() != manifest["parquet_sha256"]:
        raise ValueError("Cache file integrity failure")
    frame = pd.read_parquet(parquet)
    validate_candles(frame, request)
    if fingerprint(frame, request) != manifest["dataset_id"] or path.name != manifest["dataset_id"]:
        raise ValueError("Dataset fingerprint mismatch")
    return frame


def save_bundle(
    root: Path, frame: pd.DataFrame, request: HistoryRequest, sources: list[dict]
) -> Path:
    validate_candles(frame, request)
    dataset_id = fingerprint(frame, request)
    root.mkdir(parents=True, exist_ok=True)
    destination = root / dataset_id
    if destination.exists():
        read_bundle(destination, request)
        return destination
    with tempfile.TemporaryDirectory(prefix=".pending-", dir=root) as staging:
        temporary = Path(staging)
        parquet = temporary / "candles.parquet"
        frame.to_parquet(parquet, engine="pyarrow", compression="zstd")
        manifest = {
            "schema_version": 1,
            "dataset_id": dataset_id,
            "request": request.model_dump(mode="json"),
            "rows": len(frame),
            "sources": sources,
            "pandas_version": pd.__version__,
            "parquet_sha256": hashlib.sha256(parquet.read_bytes()).hexdigest(),
            "availability": "open_time + 1 hour; features available at close",
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        try:
            os.rename(temporary, destination)
        except OSError:
            if not destination.exists():
                raise
            read_bundle(destination, request)
    return destination


def find_bundle(root: Path, request: HistoryRequest) -> Path | None:
    matches = []
    for manifest_path in sorted(root.glob("*/manifest.json")):
        if manifest_path.parent.name.startswith("."):
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("request") == request.model_dump(mode="json"):
            read_bundle(manifest_path.parent, request)
            matches.append(manifest_path.parent)
    if len(matches) > 1:
        raise ValueError("Multiple dataset revisions: select an explicit bundle with read_bundle")
    return matches[0] if matches else None
