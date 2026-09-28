"""Read existing bundle formats, with cheap manifest checks and full content audit."""

import hashlib
import json
from datetime import UTC
from pathlib import Path

import pandas as pd

from quant_lab.history import HistoryRequest
from quant_lab.history_cache import read_bundle
from quant_lab.lab_schema import Experiment, Market
from quant_lab.study_data import HOURS, audit, digest


def history_request(raw: dict) -> HistoryRequest:
    request = HistoryRequest.model_validate_json(json.dumps(raw))
    # Pandas index.equals distinguishes Pydantic's TzInfo from standard UTC.
    # Normalize request timezone only; never alter stored timestamps or fingerprints.
    return request.model_copy(
        update={"start": request.start.astimezone(UTC), "end": request.end.astimezone(UTC)}
    )


def inspect_bundle(base: Path, market: Market) -> dict:
    path = (base / market.dataset).resolve()
    if not (path / "candles.parquet").is_file():
        raise ValueError(f"Missing local dataset: {path}; prepare data before running lab")
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    if "request" in manifest:
        request = history_request(manifest["request"])
        symbol, timeframe = request.symbol.replace("/", ""), request.timeframe
        start, end = request.download_start, request.end
        version = manifest["dataset_id"]
    else:
        quality = manifest["audit"]
        symbol, timeframe = quality["asset"], quality["timeframe"]
        start, end = quality["start"], quality["end"]
        version = quality["hash"]
        if quality["status"] == "INVALID":
            raise ValueError(f"Invalid source dataset: {path}")
    if (symbol, timeframe) != (market.symbol, market.timeframe) or path.name != version:
        raise ValueError(f"Dataset identity mismatch: {path}")
    return {
        "path": str(path),
        "dataset_id": version,
        "parquet_sha256": manifest["parquet_sha256"],
        "symbol": symbol,
        "timeframe": timeframe,
        "start": str(start),
        "end": str(end),
        "manifest": manifest,
    }


def check_periods(info: dict, market: Market, experiment: Experiment) -> None:
    step = pd.Timedelta(hours=HOURS[market.timeframe])
    for label, period in experiment.validation.periods():
        start, end = pd.Timestamp(period.start), pd.Timestamp(period.end)
        left = start - market.warmup_bars * step
        if start != start.floor(market.timeframe) or end != end.floor(market.timeframe):
            raise ValueError(f"{label}: boundaries must align to {market.timeframe}")
        if left < pd.Timestamp(info["start"]) or end > pd.Timestamp(info["end"]):
            raise ValueError(f"{market.symbol}/{market.timeframe}: {label} lacks data or warmup")
        for gap in info["manifest"].get("audit", {}).get("gaps", []):
            if pd.Timestamp(gap["start"]) < end and pd.Timestamp(gap["end"]) > left:
                raise ValueError(f"{label} overlaps a source gap; choose continuous periods")


def load_bundle(info: dict) -> pd.DataFrame:
    path = Path(info["path"])
    manifest = info["manifest"]
    if "request" in manifest:
        return read_bundle(path, history_request(manifest["request"]))
    if (
        hashlib.sha256((path / "candles.parquet").read_bytes()).hexdigest()
        != info["parquet_sha256"]
    ):
        raise ValueError(f"Dataset SHA256 mismatch: {path}")
    frame = pd.read_parquet(path / "candles.parquet")
    if digest(frame, info["symbol"], info["timeframe"]) != info["dataset_id"]:
        raise ValueError(f"Dataset fingerprint mismatch: {path}")
    report = audit(frame, info["symbol"], info["timeframe"], info["start"], info["end"])
    if report["status"] == "INVALID":
        raise ValueError(f"Dataset audit failed: {report}")
    return frame
