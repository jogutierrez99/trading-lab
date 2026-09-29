"""Read existing bundle formats, with cheap manifest checks and full content audit."""

import hashlib
import json
from datetime import UTC
from pathlib import Path

import pandas as pd

from quant_lab.history import HistoryRequest
from quant_lab.history_cache import read_bundle
from quant_lab.lab_schema import Experiment, Market
from quant_lab.study_backend import candle_step
from quant_lab.study_data import audit, digest


def history_request(raw: dict) -> HistoryRequest:
    request = HistoryRequest.model_validate_json(json.dumps(raw))
    # Pandas index.equals distinguishes Pydantic's TzInfo from standard UTC.
    # Normalize request timezone only; never alter stored timestamps or fingerprints.
    return request.model_copy(
        update={"start": request.start.astimezone(UTC), "end": request.end.astimezone(UTC)}
    )


def inspect_bundle(base: Path, market: Market) -> dict:
    path = (base / market.dataset).resolve()
    if market.dataset_format == "mtf_quarters":
        if not (path / "data.parquet").is_file():
            raise ValueError(f"Missing local dataset: {path}")
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        quality = manifest["audit"]
        if (quality["asset"], quality["timeframe"], quality["hash"]) != (
            market.symbol,
            market.timeframe,
            market.dataset_id,
        ) or quality["status"] == "INVALID":
            raise ValueError(f"Dataset identity mismatch or invalid source: {path}")
        return {
            "path": str(path),
            "dataset_id": quality["hash"],
            "parquet_sha256": manifest["sha256"],
            "symbol": market.symbol,
            "timeframe": market.timeframe,
            "start": quality["start"],
            "end": quality["end"],
            "manifest": manifest,
            "format": "mtf_quarters",
            "source_market": "USD_M_PERPETUAL_PRICES",
            "execution_note": "synthetic; no funding/liquidations",
        }
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
    if market.dataset_id is not None and market.dataset_id != version:
        raise ValueError(f"Pinned dataset identity mismatch: {path}")
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
    step = candle_step(market.timeframe)
    for label, period in experiment.validation.periods():
        start, end = pd.Timestamp(period.start), pd.Timestamp(period.end)
        left = start - market.warmup_bars * step
        if start != start.floor(step) or end != end.floor(step):
            raise ValueError(f"{label}: boundaries must align to {market.timeframe}")
        if left < pd.Timestamp(info["start"]) or end > pd.Timestamp(info["end"]):
            raise ValueError(f"{market.symbol}/{market.timeframe}: {label} lacks data or warmup")
        for gap in info["manifest"].get("audit", {}).get("gaps", []):
            if pd.Timestamp(gap["start"]) < end and pd.Timestamp(gap["end"]) > left:
                raise ValueError(f"{label} overlaps a source gap; choose continuous periods")


def load_bundle(info: dict) -> pd.DataFrame:
    path = Path(info["path"])
    manifest = info["manifest"]
    if info.get("format") == "mtf_quarters":
        from quant_lab.mtf_data import quarter_audit

        parquet = path / "data.parquet"
        if hashlib.sha256(parquet.read_bytes()).hexdigest() != info["parquet_sha256"]:
            raise ValueError(f"Dataset SHA256 mismatch: {path}")
        frame = pd.read_parquet(parquet)
        report = quarter_audit(frame, info["symbol"])
        if report["hash"] != info["dataset_id"] or report["status"] == "INVALID":
            raise ValueError(f"Dataset fingerprint/audit mismatch: {path}")
        if any(pd.Timestamp(report[k]) != pd.Timestamp(info[k]) for k in ("start", "end")):
            raise ValueError(f"Dataset coverage mismatch: {path}")
        return frame
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
