"""Derive a source manifest and validate a continuous subset of audited monthly CSVs."""

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from quant_lab.binance_history import BASE_URL, retain_bytes
from quant_lab.config import load_yaml
from quant_lab.csv_history import load_csv_history
from quant_lab.history import HistoryRequest
from quant_lab.history_cache import save_bundle


def prepare(config: Path, audit: Path, csv_dir: Path, cache: Path, reports: Path) -> Path:
    request = load_yaml(config, HistoryRequest)
    payload = audit.read_bytes()
    parent = json.loads(payload)
    previous = HistoryRequest.model_validate_json(json.dumps(parent["request"]))
    if (request.provider, request.market_type, request.symbol, request.timeframe) != (
        previous.provider,
        previous.market_type,
        previous.symbol,
        previous.timeframe,
    ) or not previous.download_start.replace(
        day=1, hour=0
    ) <= request.download_start < request.end <= previous.end:
        raise ValueError("Subset must retain market and remain inside audited source range")
    by_url = {s["url"]: s for s in parent["sources"]}
    if len(by_url) != len(parent["sources"]):
        raise ValueError("Duplicate source URLs")
    sources = []
    month = request.download_start.replace(day=1, hour=0)
    symbol = request.symbol.replace("/", "")
    while month < request.end:
        url = f"{BASE_URL}/{symbol}/1h/{symbol}-1h-{month:%Y-%m}.zip"
        if url not in by_url:
            raise ValueError(f"Missing source: {url}")
        sources.append(by_url[url])
        month = (month.replace(day=28) + pd.Timedelta(days=4)).replace(day=1)
    manifest = {
        "request": request.model_dump(mode="json"),
        "sources": sources,
        "parent_manifest_sha256": hashlib.sha256(payload).hexdigest(),
        "status": "subset_pending_revalidation",
    }
    body = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    manifest_path = reports / f"subset-{hashlib.sha256(body).hexdigest()}.json"
    retain_bytes(manifest_path, body)
    frame, checked, report = load_csv_history(request, manifest_path, csv_dir, reports)
    bundle = save_bundle(cache, frame, request, checked)
    print(
        json.dumps(
            {
                "bundle": str(bundle.resolve()),
                "rows": len(frame),
                "quality_report": str(report.resolve()),
                "manifest": str(manifest_path.resolve()),
            }
        )
    )
    return bundle


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--csv-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/history"))
    parser.add_argument("--report-dir", type=Path, default=Path("reports/history-subsets"))
    args = parser.parse_args()
    prepare(args.config, args.audit, args.csv_dir, args.cache_dir, args.report_dir)
