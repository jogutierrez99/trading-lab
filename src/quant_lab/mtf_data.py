"""Reuse Batch006 frozen data; independently audit finer USD-M bars where necessary."""

import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from quant_lab.batch_006 import load_common
from quant_lab.experiments import write_json
from quant_lab.futures_data import BASE, source_page
from quant_lab.mtf_clock import clock_frame, stretch
from quant_lab.study_data import COLUMNS, audit, digest, pages

PREVIOUS = Path("results/batch_006_bollinger_long_short/20260926T103758Z-dd7672b4fa25")
QUARTERS = Path("data/mtf_15m")


def prior_plan():
    return json.loads((PREVIOUS / "plan.json").read_text(encoding="utf-8"))


def load_frozen():
    data, quality = load_common()
    previous = prior_plan()
    for asset, dataset in data.items():
        for tf, frame in dataset["frames"].items():
            frozen = next(
                v
                for v in previous["used_data"]
                if v["asset"] == asset + "_USD_M_PERPETUAL" and v["timeframe"] == tf
            )
            if audit(frame, asset + "_USD_M_PERPETUAL", tf)["hash"] != frozen["hash"]:
                raise ValueError("Current data differs from frozen Batch006 identity")
    return data, quality


def quarter_audit(frame, asset):
    report = audit(clock_frame(frame, 4), asset, "1h")
    for field in ("start", "end"):
        if field in report:
            report[field] = str(stretch(pd.Timestamp(report[field]), 0.25))
    for gap in report.get("gaps", []):
        for field in ("start", "end"):
            gap[field] = str(stretch(pd.Timestamp(gap[field]), 0.25))
    report.update(timeframe="15m", hash=digest(frame, asset, "15m"))
    return report


def parse_quarters(payload):
    if payload.splitlines()[0].split(b",")[0] in (b"open_time", b"openTime"):
        payload = payload.split(b"\n", 1)[1]
    raw = pd.read_csv(io.BytesIO(payload), header=None)
    if raw.shape[1] != 12 or raw.empty:
        raise ValueError("Expected Binance 12-column bars")
    unit = "us" if raw.iloc[0, 0] > 10**14 else "ms"
    idx = pd.DatetimeIndex(pd.to_datetime(raw[0], unit=unit, utc=True), name="open_time")
    closes = pd.DatetimeIndex(pd.to_datetime(raw[6], unit=unit, utc=True))
    valid = (
        (idx == idx.floor("15min")) & (closes >= idx) & (closes < idx + pd.Timedelta(minutes=15))
    )
    f = raw.iloc[:, 1:6].astype(float)
    f.columns = COLUMNS
    f.index = idx
    f = f.loc[valid].copy()
    f.attrs["quarantined"] = [str(t) for t in idx[~valid]]
    return f


def download_quarters(asset, kind, start, end):
    directory = QUARTERS / asset / kind
    if (directory / "manifest.json").exists():
        return str(directory)
    frames = []
    sources = []
    errors = []
    for cadence, stamp, _left, _right in pages(start, end):
        name = f"{asset}-15m-{stamp}"
        url = f"{BASE}/{cadence}/{kind}/{asset}/15m/{name}.zip"
        try:
            payload, source = source_page(directory, url, name)
            frame = parse_quarters(payload)
            report = quarter_audit(frame, asset)
            if report["status"] == "INVALID":
                raise ValueError(str(report))
            sources.append(source | {"quarantined": frame.attrs.get("quarantined", [])})
            frame.attrs = {}
            frames.append(frame)
        except (RuntimeError, ValueError, OSError) as exc:
            errors.append({"url": url, "error": str(exc)})
    if not frames:
        raise ValueError("No quarter-hour data available")
    frame = pd.concat(frames).sort_index()
    report = quarter_audit(frame, asset)
    if report["status"] == "INVALID":
        raise ValueError(str(report))
    directory.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(directory / "data.parquet")
    write_json(
        directory / "manifest.json",
        {
            "sources": sources,
            "errors": errors,
            "audit": report,
            "sha256": hashlib.sha256((directory / "data.parquet").read_bytes()).hexdigest(),
        },
    )
    print("QUARTERS", asset, kind, len(frame), flush=True)
    return str(directory)


def download_all_quarters():
    plan = prior_plan()
    start = plan["splits"][0][1]
    end = plan["splits"][-1][2]
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = [
            pool.submit(download_quarters, a, k, start, end)
            for a in ("BTCUSDT", "ETHUSDT")
            for k in ("klines", "markPriceKlines")
        ]
        return [t.result() for t in tasks]


def load_quarters(data, matched=False):
    reports = {}
    excluded = set()
    for asset, item in data.items():
        reports[asset] = {}
        for kind, target, reference in (
            ("klines", "quarter", item["frames"]["1h"]),
            ("markPriceKlines", "quarter_mark", item["mark"]),
        ):
            root = QUARTERS / asset / kind
            meta = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            if hashlib.sha256((root / "data.parquet").read_bytes()).hexdigest() != meta["sha256"]:
                raise ValueError("Quarter source hash mismatch")
            full = pd.read_parquet(root / "data.parquet")
            frame = full.loc[full.index.floor("h").isin(reference.index)]
            report = quarter_audit(frame, asset)
            grouped = frame.resample("h")
            aggregated = grouped.agg(
                {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
            )
            aggregate = aggregated.loc[grouped.size() == 4]
            missing = reference.index.difference(aggregate.index)
            common = reference.index.intersection(aggregate.index)
            # None of the frozen strategies or risk rules uses volume.
            fields = COLUMNS[:4]
            bad = ~np.isclose(
                aggregate.loc[common, fields], reference.loc[common, fields], rtol=1e-12, atol=1e-8
            ).all(axis=1)
            volume_bad = ~np.isclose(
                aggregate.loc[common, "volume"],
                reference.loc[common, "volume"],
                rtol=1e-12,
                atol=1e-8,
            )
            report.update(
                missing_frozen_hours=[str(t) for t in missing],
                aggregation_mismatches=[str(t) for t in common[bad]],
                unused_volume_mismatches=[str(t) for t in common[volume_bad]],
                source=meta,
            )
            reports[asset][kind] = report
            if report["status"] == "INVALID":
                raise ValueError("Invalid quarter OHLCV")
            excluded.update(missing.floor("D"))
            excluded.update(common[bad].floor("D"))
            item[target] = frame
    if excluded and not matched:
        raise ValueError(
            "Quarter data needs an explicitly matched cohort; original baseline retained"
        )
    for item in data.values():
        item["frames"] = {
            tf: f.loc[~f.index.floor("D").isin(excluded)] for tf, f in item["frames"].items()
        }
        for field in ("mark", "funding", "quarter", "quarter_mark"):
            item[field] = item[field].loc[~item[field].index.floor("D").isin(excluded)]
    reports["excluded_days"] = [str(t) for t in sorted(excluded)]
    reports["policy"] = (
        "Symmetric exclusion for every asset/version in the matched cohort"
        " only. Original V1/V2 remain intact."
    )
    return reports
