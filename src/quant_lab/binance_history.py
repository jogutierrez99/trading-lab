"""Public monthly Binance spot archives with SHA256 verification. No credentials."""

import hashlib
import io
import json
import logging
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from quant_lab.candles import COLUMNS, validate_candles
from quant_lab.history import HistoryRequest

logger = logging.getLogger(__name__)
BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"


def fetch_bytes(url: str) -> bytes:
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise RuntimeError(f"Archive request failed: HTTP {exc.code}: {url}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == 2:
                raise RuntimeError(f"Archive request failed: {url}: {exc}") from exc
        time.sleep(2**attempt)
    raise AssertionError("unreachable")


def archive_csv(payload: bytes, filename: str) -> bytes:
    """Read exactly one named member; never extract archive paths to disk."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if archive.namelist() != [filename]:
            raise ValueError(f"Unexpected archive members for {filename}")
        return archive.read(filename)


def parse_archive(payload: bytes, filename: str, microseconds: bool) -> pd.DataFrame:
    return parse_csv(archive_csv(payload, filename), filename, microseconds)


def parse_csv(payload: bytes, filename: str, microseconds: bool) -> pd.DataFrame:
    """Parse the original 12-column Binance CSV without repairing observations."""
    raw = pd.read_csv(io.BytesIO(payload), header=None)
    if raw.shape[1] != 12 or raw.empty:
        raise ValueError(f"Invalid Binance kline layout: {filename}")
    unit = "us" if microseconds else "ms"
    opens = pd.to_datetime(raw[0], unit=unit, utc=True)
    closes = pd.to_datetime(raw[6], unit=unit, utc=True)
    epsilon = pd.Timedelta(microseconds=1) if microseconds else pd.Timedelta(milliseconds=1)
    if not ((closes >= opens) & (closes < opens + pd.Timedelta(hours=1))).all():
        raise ValueError(f"Invalid candle close timestamps: {filename}")
    frame = raw.iloc[:, 1:6].astype("float64")
    frame.columns = COLUMNS
    frame.index = pd.DatetimeIndex(opens, name="open_time")
    early = closes != opens + pd.Timedelta(hours=1) - epsilon
    frame.attrs["early_source_closes"] = [
        {"open_time": opens[i].isoformat(), "source_close_time": closes[i].isoformat()}
        for i in raw.index[early]
    ]
    return frame


def download_history(
    request: HistoryRequest,
    fetch: Callable[[str], bytes] = fetch_bytes,
    archive_dir: Path | None = None,
    csv_dir: Path | None = None,
) -> tuple[pd.DataFrame, list[dict]]:
    if request.end > datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0):
        raise ValueError("Monthly provider only supports completed months")
    symbol = request.symbol.replace("/", "")
    month = request.download_start.replace(day=1, hour=0)
    frames, sources, issues = [], [], []
    while month < request.end:
        name = f"{symbol}-1h-{month:%Y-%m}"
        url = f"{BASE_URL}/{symbol}/1h/{name}.zip"
        payload = fetch(url)
        checksum = fetch(url + ".CHECKSUM").decode("ascii").split()
        digest = hashlib.sha256(payload).hexdigest()
        if len(checksum) != 2 or checksum[0] != digest or checksum[1] != name + ".zip":
            raise ValueError(f"Archive checksum mismatch: {url}")
        if archive_dir is not None:
            retain_bytes(archive_dir / f"{digest}.zip", payload)
        next_month = (month.replace(day=28) + pd.Timedelta(days=4)).replace(day=1)
        month_request = request.model_copy(
            update={"start": month, "end": next_month, "warmup_bars": 0}
        )
        source = {"url": url, "sha256": digest}
        sources.append(source)
        try:
            csv = archive_csv(payload, name + ".csv")
            if csv_dir is not None:
                retain_bytes(csv_dir / digest / (name + ".csv"), csv)
                source["csv_sha256"] = hashlib.sha256(csv).hexdigest()
            frame = parse_csv(csv, name + ".csv", month.year >= 2025)
            source["early_source_closes"] = frame.attrs["early_source_closes"]
            validate_candles(frame, month_request)
        except ValueError as exc:
            issue = {"month": f"{month:%Y-%m}", "error": str(exc)}
            issues.append(issue)
            logger.error(json.dumps({"event": "archive_rejected", **issue}))
            month = next_month
            continue
        frames.append(
            frame.loc[(frame.index >= request.download_start) & (frame.index < request.end)]
        )
        anomalies = frame.attrs["early_source_closes"]
        if anomalies:
            logger.warning(
                json.dumps(
                    {
                        "event": "early_source_close",
                        "month": f"{month:%Y-%m}",
                        "candles": anomalies,
                        "availability": "scheduled hour end; never source close",
                    }
                )
            )
        logger.info(json.dumps({"event": "archive_validated", "month": f"{month:%Y-%m}"}))
        month = next_month
    if csv_dir is not None:
        manifest = {
            "schema_version": 1,
            "request": request.model_dump(mode="json"),
            "sources": sources,
            "status": "rejected" if issues else "source_months_validated",
        }
        body = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
        path = csv_dir / f"manifest-{hashlib.sha256(body).hexdigest()}.json"
        retain_bytes(path, body)
        logger.info(json.dumps({"event": "csv_manifest", "path": str(path.resolve())}))
    if issues:
        report = {
            "request": request.model_dump(mode="json"),
            "sources": sources,
            "issues": issues,
            "status": "rejected",
            "schema_version": 1,
        }
        if archive_dir is not None:
            body = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
            report_path = archive_dir / f"quality-{hashlib.sha256(body).hexdigest()}.json"
            retain_bytes(report_path, body)
            logger.error(
                json.dumps({"event": "quality_report", "path": str(report_path.resolve())})
            )
        raise ValueError(f"Historical data rejected: {json.dumps(issues)}")
    result = pd.concat(frames)
    result.attrs = {}
    validate_candles(result, request)
    return result, sources


def retain_bytes(path: Path, payload: bytes) -> None:
    """Retain source/audit bytes exclusively; never overwrite a historical artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as file:
            file.write(payload)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise ValueError(f"Existing source artifact is corrupt: {path}") from None
