"Public USD-M perpetual archives, mark prices and observed funding; never spot."

import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import pandas as pd

from quant_lab.binance_history import archive_csv, fetch_bytes, retain_bytes
from quant_lab.study_data import HOURS, aggregate_check, audit, pages, parse

ROOT = Path("data/batch_006_perpetual")
BASE = "https://data.binance.vision/data/futures/um"


def funding_frame(payload):
    raw = pd.read_csv(io.BytesIO(payload))
    required = {"calc_time", "funding_interval_hours", "last_funding_rate"}
    if not required.issubset(raw.columns):
        raise ValueError("Unexpected funding layout")
    frame = pd.DataFrame(
        {
            "rate": raw.last_funding_rate.astype(float).to_numpy(),
            "interval_hours": raw.funding_interval_hours.astype(float).to_numpy(),
        },
        index=pd.DatetimeIndex(
            pd.to_datetime(raw.calc_time, unit="ms", utc=True), name="funding_time"
        ),
    )
    validate_funding(frame)
    return frame


def validate_funding(frame):
    if (
        frame.empty
        or str(frame.index.tz) != "UTC"
        or not frame.index.is_monotonic_increasing
        or not frame.index.is_unique
    ):
        raise ValueError("Invalid funding timestamps")
    if (
        not np.isfinite(frame.to_numpy()).all()
        or (frame.rate.abs() >= 1).any()
        or (frame.interval_hours <= 0).any()
    ):
        raise ValueError("Invalid funding values")


def source_page(directory, url, name, fetch=fetch_bytes):
    checkpoint = directory / "pages" / (name + ".json")
    if checkpoint.exists():
        source = json.loads(checkpoint.read_text())
        payload = (directory / "raw" / (source["sha256"] + ".zip")).read_bytes()
        if source["url"] != url or hashlib.sha256(payload).hexdigest() != source["sha256"]:
            raise ValueError("Corrupt immutable source")
    else:
        payload = fetch(url)
        sha = hashlib.sha256(payload).hexdigest()
        if fetch(url + ".CHECKSUM").decode().split() != [sha, name + ".zip"]:
            raise ValueError("Archive checksum mismatch")
        source = {"url": url, "sha256": sha, "retrieved": datetime.now(UTC).isoformat()}
        retain_bytes(directory / "raw" / (sha + ".zip"), payload)
        retain_bytes(checkpoint, json.dumps(source).encode())
    return archive_csv(payload, name + ".csv"), source


def parse_klines(payload, tf):
    # USD-M archives started carrying headers in later years.
    first = payload.splitlines()[0].split(b",")[0]
    if first in (b"open_time", b"openTime"):
        payload = payload.split(b"\n", 1)[1]
    return parse(payload, tf)


def download_series(root, asset, kind, tf, start, end, fetch=fetch_bytes):
    directory = root / asset / kind / tf
    directory.mkdir(parents=True, exist_ok=True)
    frames, sources, errors = [], [], []
    for cadence, stamp, _left, _right in pages(start, end):
        if kind == "fundingRate" and cadence == "daily":
            continue
        name = f"{asset}-{kind if kind == 'fundingRate' else tf}-{stamp}"
        branch = asset if kind == "fundingRate" else f"{asset}/{tf}"
        url = f"{BASE}/{cadence}/{kind}/{branch}/{name}.zip"
        try:
            raw, source = source_page(directory, url, name, fetch)
            frame = funding_frame(raw) if kind == "fundingRate" else parse_klines(raw, tf)
            if kind != "fundingRate":
                quality = audit(frame, asset + "_USD_M_PERPETUAL_" + kind, tf)
                if quality["status"] == "INVALID":
                    raise ValueError(str(quality))
                source = source | {
                    "quarantined_timestamps": frame.attrs.get("quarantined_source_timestamps", [])
                }
            frame.attrs = {}
            frames.append(frame)
            sources.append(source)
        except (RuntimeError, ValueError, OSError) as exc:
            error = {"url": url, "error": str(exc)}
            errors.append(error)
            with (directory / "errors.jsonl").open("a", encoding="utf-8") as out:
                out.write(json.dumps(error) + "\n")
    if not frames:
        raise ValueError(f"No reliable {asset}/{kind}/{tf}")
    frame = pd.concat(frames).sort_index()
    if not frame.index.is_unique:
        raise ValueError("Duplicate source timestamps")
    body = frame.to_json(date_format="iso", double_precision=15).encode()
    sha = hashlib.sha256(f"USD_M_PERPETUAL/{asset}/{kind}/{tf}".encode() + body).hexdigest()
    target = directory / sha
    target.mkdir(exist_ok=True)
    parquet = target / "data.parquet"
    if parquet.exists():
        pd.testing.assert_frame_equal(pd.read_parquet(parquet), frame)
    else:
        frame.to_parquet(parquet)
    metadata = {
        "exchange": "binance",
        "market_type": "USD_M_PERPETUAL",
        "asset": asset,
        "kind": kind,
        "timeframe": tf,
        "start": str(frame.index[0]),
        "end": str(frame.index[-1]),
        "rows": len(frame),
        "sources": sources,
        "errors": errors,
        "hash": sha,
        "parquet_sha256": hashlib.sha256(parquet.read_bytes()).hexdigest(),
    }
    if not (target / "manifest.json").exists():
        retain_bytes(target / "manifest.json", json.dumps(metadata, indent=2).encode())
    print(f"DATA {asset}/{kind}/{tf}: {len(frame)}", flush=True)
    return str(target)


def funding_tail(root, asset, start, end, fetch=fetch_bytes):
    "REST pagination retains actual funding rates/mark prices; no estimated rates."
    directory = root / asset / "funding_rest"
    directory.mkdir(parents=True, exist_ok=True)
    cursor = int(pd.Timestamp(start).timestamp() * 1000)
    stop = int(pd.Timestamp(end).timestamp() * 1000)
    records = []
    while cursor < stop:
        path = directory / f"{cursor}-{stop}.json"
        url = "https://fapi.binance.com/fapi/v1/fundingRate?" + urlencode(
            {"symbol": asset, "startTime": cursor, "endTime": stop - 1, "limit": 1000}
        )
        try:
            payload = path.read_bytes() if path.exists() else fetch(url)
            rows = json.loads(payload)
            if not isinstance(rows, list):
                raise ValueError("Unexpected funding response")
            retain_bytes(path, payload)
            if not rows:
                break
            if any(
                r["symbol"] != asset or not cursor <= int(r["fundingTime"]) < stop for r in rows
            ):
                raise ValueError("Funding pagination identity or bounds mismatch")
            records.extend(rows)
            next_cursor = max(int(r["fundingTime"]) for r in rows) + 1
            if next_cursor <= cursor:
                raise ValueError("Funding pagination did not advance")
            cursor = next_cursor
        except (RuntimeError, ValueError, OSError) as exc:
            retain_bytes(
                directory / f"error-{datetime.now(UTC):%Y%m%dT%H%M%S}.json",
                json.dumps({"url": url, "error": str(exc)}).encode(),
            )
            print(f"FUNDING TAIL unavailable {asset}: {exc}", flush=True)
            break
    return records


def download_all(root=ROOT, start="2019-09-01T00:00:00Z", end=None):
    end = end or datetime.now(UTC).strftime("%Y-%m-%dT00:00:00Z")
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = [
            pool.submit(download_series, root, a, k, tf, start, end)
            for a in ("BTCUSDT", "ETHUSDT")
            for k, tf in [("klines", t) for t in HOURS]
            + [("markPriceKlines", "1h"), ("fundingRate", "events")]
        ]
        result = [job.result() for job in jobs]
    for asset in ("BTCUSDT", "ETHUSDT"):
        funding_tail(root, asset, pd.Timestamp(end).replace(day=1), end)
    return result


def load_one(root, asset, kind, tf):
    paths = list((root / asset / kind / tf).glob("*/manifest.json"))
    path = max(paths, key=lambda p: json.loads(p.read_text())["rows"])
    meta = json.loads(path.read_text())
    parquet = path.parent / "data.parquet"
    if hashlib.sha256(parquet.read_bytes()).hexdigest() != meta["parquet_sha256"]:
        raise ValueError("Dataset checksum failure")
    return pd.read_parquet(parquet), meta


def load_audited(root=ROOT):
    datasets, report = {}, {}
    for asset in ("BTCUSDT", "ETHUSDT"):
        frames, metadata = {}, {}
        for tf in HOURS:
            frames[tf], metadata[tf] = load_one(root, asset, "klines", tf)
        mark, metadata["mark"] = load_one(root, asset, "markPriceKlines", "1h")
        fund, metadata["funding"] = load_one(root, asset, "fundingRate", "events")
        tails = []
        for p in (root / asset / "funding_rest").glob("*.json"):
            if p.name.startswith("error"):
                continue
            tails.extend(json.loads(p.read_text()))
        if tails:
            records = pd.DataFrame(tails)
            conflicts = records.groupby("fundingTime").fundingRate.nunique()
            if (conflicts > 1).any():
                raise ValueError("Conflicting retained funding observations")
            records = records.drop_duplicates("fundingTime").sort_values("fundingTime")
            tail = pd.DataFrame(
                {"rate": records.fundingRate.astype(float).to_numpy(), "interval_hours": 8.0},
                index=pd.DatetimeIndex(
                    pd.to_datetime(records.fundingTime, unit="ms", utc=True), name="funding_time"
                ),
            )
            # Interval is verified from observed timestamps below, never used to invent events.
            fund = pd.concat([fund, tail.loc[tail.index > fund.index[-1]]])
            metadata["funding_rest"] = {
                str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (root / asset / "funding_rest").glob("*.json")
                if not p.name.startswith("error")
            }
        validate_funding(fund)
        offsets = (fund.index - fund.index.floor("h")).total_seconds()
        if (offsets >= 1).any():
            raise ValueError("Funding offset>=1s needs finer execution data")
        if fund.index.floor("h").duplicated().any():
            raise ValueError("Multiple funding settlements in an execution hour")
        metadata["funding_timestamp_offset_seconds_max"] = float(offsets.max())
        common = None
        for tf, frame in frames.items():
            quality = audit(frame, asset + "_PERPETUAL", tf)
            if quality["status"] == "INVALID":
                raise ValueError(str(quality))
            count = frame.groupby(frame.index.floor("D")).size()
            days = count.index[count == 24 // HOURS[tf]]
            common = days if common is None else common.intersection(days)
        if audit(mark, asset + "_MARK", "1h")["status"] == "INVALID":
            raise ValueError("Invalid mark prices")
        count = mark.groupby(mark.index.floor("D")).size()
        common = common.intersection(count.index[count == 24])
        checks = {tf: aggregate_check(frames["1h"], frames[tf], tf) for tf in ("4h", "1d")}
        for check in checks.values():
            common = common.difference(
                pd.DatetimeIndex([pd.Timestamp(d) for d in check["mismatch_days"]])
            )
        # Funding coverage is audited by actual interval chains, not assumed zero in holes.
        covered = []
        event_set = set(fund.index.floor("h"))
        for day in common:
            expected = [day + pd.Timedelta(hours=h) for h in (0, 8, 16)]
            if all(t in event_set for t in expected):
                covered.append(day)
        common = pd.DatetimeIndex(covered)
        if len(common) < 730:
            raise ValueError("Insufficient funding-complete perpetual history")
        datasets[asset] = {
            "frames": {tf: f.loc[f.index.floor("D").isin(common)] for tf, f in frames.items()},
            "mark": mark.loc[mark.index.floor("D").isin(common)],
            "funding": fund.loc[fund.index.floor("D").isin(common)],
        }
        report[asset] = {
            "metadata": metadata,
            "aggregation": checks,
            "funding_status": "HISTORICAL_FUNDING",
            "funding_policy": (
                "Keep only complete UTC days with observed settlements within1s "
                "of00/08/16UTC; actual timestamps retained. No zero-fill. Mark-"
                "open quote proxy, offset<1s. Exact-boundary funding precedes "
                "opening fills; delayed settlements follow opening actions and "
                "precede intrabar fills."
            ),
            "common_days": len(common),
            "start": str(common[0]),
            "end": str(common[-1] + pd.Timedelta(days=1)),
        }
    return datasets, report
