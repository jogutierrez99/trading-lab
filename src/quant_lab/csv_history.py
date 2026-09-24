"""Offline import of original Binance monthly CSVs with explicit source provenance."""

import hashlib
import json
import re
from pathlib import Path

import pandas as pd

from quant_lab.binance_history import BASE_URL, parse_csv, retain_bytes
from quant_lab.candles import validate_candles
from quant_lab.history import HistoryRequest


def load_csv_history(
    request: HistoryRequest, manifest_path: Path, csv_dir: Path, report_dir: Path
) -> tuple[pd.DataFrame, list[dict], Path]:
    """Check all full months, then the requested range; never fill missing candles.

    Accept downloader CSV manifests and extraction audit manifests containing the
    same request/sources contract. Paths are derived locally, never taken from JSON.
    Manifest hashes establish integrity relative to the supplied local provenance;
    this offline operation does not authenticate provenance against Binance again.
    """
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict) or manifest.get("request") != request.model_dump(mode="json"):
        raise ValueError("CSV manifest request mismatch")
    sources = manifest.get("sources")
    if not isinstance(sources, list):
        raise ValueError("CSV manifest must contain sources")
    symbol = request.symbol.replace("/", "")
    month = request.download_start.replace(day=1, hour=0)
    expected = {}
    while month < request.end:
        name = f"{symbol}-1h-{month:%Y-%m}"
        url = f"{BASE_URL}/{symbol}/1h/{name}.zip"
        next_month = (month.replace(day=28) + pd.Timedelta(days=4)).replace(day=1)
        expected[url] = (name + ".csv", month, next_month)
        month = next_month
    indexed = {}
    for source in sources:
        if (
            not isinstance(source, dict)
            or not isinstance(source.get("url"), str)
            or source["url"] not in expected
        ):
            raise ValueError("Unexpected source in CSV manifest")
        url = source["url"]
        if url in indexed:
            raise ValueError("Duplicate source in CSV manifest")
        for field in ("sha256", "csv_sha256"):
            if not isinstance(source.get(field), str) or not re.fullmatch(
                r"[0-9a-f]{64}", source[field]
            ):
                raise ValueError(f"Invalid or missing {field} in CSV manifest")
        indexed[url] = source
    if indexed.keys() != expected.keys():
        raise ValueError("CSV manifest does not contain every requested source month")

    frames, issues, checked = [], [], []
    for url, (filename, start, end) in expected.items():
        source = indexed[url]
        path = csv_dir / source["sha256"] / filename
        try:
            payload = path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != source["csv_sha256"]:
                raise ValueError("CSV checksum mismatch")
            frame = parse_csv(payload, filename, start.year >= 2025)
            checked.append({"url": url, "rows": len(frame)})
            month_request = request.model_copy(
                update={"start": start, "end": end, "warmup_bars": 0}
            )
            validate_candles(frame, month_request)
            frames.append(
                frame.loc[(frame.index >= request.download_start) & (frame.index < request.end)]
            )
        except (ValueError, OSError) as exc:
            issues.append({"month": f"{start:%Y-%m}", "error": str(exc)})
    result = None
    if not issues:
        result = pd.concat(frames)
        result.attrs = {}
        validate_candles(result, request)
    report = {
        "schema_version": 1,
        "request": request.model_dump(mode="json"),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "sources": sources,
        "checked": checked,
        "issues": issues,
        "status": "rejected" if issues else "validated",
        "rows": len(result) if result is not None else None,
    }
    body = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    report_path = report_dir / f"csv-quality-{hashlib.sha256(body).hexdigest()}.json"
    retain_bytes(report_path, body)
    if issues:
        raise ValueError(
            f"CSV history rejected: {json.dumps(issues)}; report: {report_path.resolve()}"
        )
    assert result is not None
    return result, sources, report_path
