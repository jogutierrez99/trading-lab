"""Read-only automatic inventory of local bundles and Binance candle CSVs."""

import hashlib
import json
import re
from datetime import UTC
from pathlib import Path

import pandas as pd

from quant_lab.history import HistoryRequest
from quant_lab.history_cache import read_bundle


def inventory(repo: Path) -> dict:
    bundles, csvs = [], []
    boundary = pd.Timestamp("2026-01-01", tz="UTC")
    for path in sorted((repo / "data/history").glob("*/manifest.json")):
        manifest = json.loads(path.read_text())
        request = HistoryRequest.model_validate_json(json.dumps(manifest["request"]))
        request = request.model_copy(
            update={"start": request.start.astimezone(UTC), "end": request.end.astimezone(UTC)}
        )
        frame = read_bundle(path.parent, request)
        sources = manifest["sources"]
        for source in sources:
            if "csv_path" in source:
                if (
                    hashlib.sha256((repo / source["csv_path"]).read_bytes()).hexdigest()
                    != source["csv_sha256"]
                ):
                    raise ValueError("Source CSV hash differs from audited manifest")
        bundles.append(
            {
                "path": str(path.relative_to(repo)),
                "symbol": request.symbol,
                "timeframe": request.timeframe,
                "first": str(frame.index[0]),
                "last": str(frame.index[-1]),
                "rows": len(frame),
                "warmup": request.warmup_bars,
                "gaps": 0,
                "dataset_id": manifest["dataset_id"],
                "parquet_sha256": manifest["parquet_sha256"],
                "sources": sources,
                "previously_observed": request.symbol == "BTC/USDT" and request.end <= boundary,
            }
        )
    # Inspect timestamps, not just filenames; unrecognized CSVs are recorded explicitly.
    for path in sorted((repo / "data").rglob("*.csv")):
        match = re.match(r"([A-Z0-9]+USDT)-1h-", path.name)
        record = {
            "path": str(path.relative_to(repo)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        if not match:
            csvs.append(record | {"status": "unrecognized_format"})
            continue
        raw = pd.to_numeric(pd.read_csv(path, header=None, usecols=[0]).iloc[:, 0], errors="raise")
        unit = "us" if raw.max() > 1e14 else "ms" if raw.max() > 1e11 else "s"
        dates = pd.DatetimeIndex(pd.to_datetime(raw, unit=unit, utc=True))
        csvs.append(
            record
            | {
                "status": "timestamp_inventory_only",
                "symbol": match[1],
                "rows": len(raw),
                "first": str(dates.min()),
                "last": str(dates.max()),
                "has_post_2026_btc": match[1] == "BTCUSDT" and bool((dates >= boundary).any()),
                "is_alternative": match[1] != "BTCUSDT",
            }
        )
    fresh = any(x.get("has_post_2026_btc") or x.get("is_alternative") for x in csvs) or any(
        b["symbol"] != "BTC/USDT" or pd.Timestamp(b["last"]) >= boundary for b in bundles
    )
    return {
        "bundles": bundles,
        "csv_files": csvs,
        "fresh_or_alternative_available": fresh,
        "decision": "NEW_DATA_REQUIRES_AUDITED_FROZEN_SPLITS"
        if fresh
        else "REUSED_HISTORY_DIAGNOSTIC",
        "scope": "Local data only; no download or external claim about market data availability. "
        "This frozen preset must stop if new BTC/alternative appears "
        "rather than silently reuse history.",
    }
