"""Independent, resumable public archive ingestion for the cross-market study."""

import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from quant_lab.binance_history import archive_csv, fetch_bytes, retain_bytes

HOURS = {"1h": 1, "4h": 4, "1d": 24}
COLUMNS = ["open", "high", "low", "close", "volume"]


def hours_to_bars(hours: int, timeframe: str) -> int:
    if type(hours) is not int or hours <= 0 or hours % HOURS[timeframe]:
        raise ValueError(f"Duration {hours}h is not exactly representable at {timeframe}")
    return hours // HOURS[timeframe]


def days_to_bars(days: int, timeframe: str) -> int:
    if type(days) is not int:
        raise ValueError("Days must be an integer")
    return hours_to_bars(days * 24, timeframe)


def digest(frame, asset, timeframe):
    head = f"{asset}/{timeframe}/UTC/OHLCV/v1".encode()
    return hashlib.sha256(
        head
        + frame.index.as_unit("ns").asi8.astype("<i8").tobytes()
        + frame[COLUMNS].to_numpy(dtype="<f8").tobytes()
    ).hexdigest()


def audit(frame, asset, timeframe, start=None, end=None):
    step = pd.Timedelta(hours=HOURS[timeframe])
    issues = []
    if frame.empty:
        return {
            "asset": asset,
            "timeframe": timeframe,
            "rows": 0,
            "status": "INVALID",
            "issues": ["empty"],
        }
    if str(frame.index.tz) != "UTC":
        issues.append("timestamps_not_UTC")
    if not frame.index.is_monotonic_increasing:
        issues.append("timestamps_not_sorted")
    duplicates = int(frame.index.duplicated().sum())
    if duplicates:
        issues.append("duplicate_timestamps")
    if (frame.index != frame.index.floor(timeframe)).any():
        issues.append("off_grid_timestamps")
    values = frame[COLUMNS]
    bad = (
        ~np.isfinite(values).all(axis=1)
        | (values[COLUMNS[:4]] <= 0).any(axis=1)
        | (frame.volume < 0)
        | (frame.high < frame.low)
        | (frame.open < frame.low)
        | (frame.open > frame.high)
        | (frame.close < frame.low)
        | (frame.close > frame.high)
    )
    if bad.any():
        issues.append("invalid_OHLCV")
    start = pd.Timestamp(start) if start is not None else frame.index.min()
    end = pd.Timestamp(end) if end is not None else frame.index.max() + step
    expected = pd.date_range(start, end, freq=timeframe, inclusive="left")
    missing = expected.difference(frame.index)
    if len(frame.index.difference(expected)):
        issues.append("outside_requested_interval")
    gaps = []
    if len(missing):
        for _, group in pd.Series(missing, index=missing).groupby(
            (pd.Series(missing).diff() != step).cumsum().to_numpy()
        ):
            gaps.append(
                {"start": str(group.iloc[0]), "end": str(group.iloc[-1] + step), "bars": len(group)}
            )
    return {
        "asset": asset,
        "timeframe": timeframe,
        "start": str(start),
        "end": str(end),
        "rows": len(frame),
        "expected_rows": len(expected),
        "missing_bars": len(missing),
        "duplicate_bars": duplicates,
        "largest_gap": max((g["bars"] for g in gaps), default=0),
        "largest_gap_unit": "bars",
        "hash": digest(frame, asset, timeframe),
        "status": "INVALID" if issues else "VALID_WITH_GAPS" if len(missing) else "VALID",
        "issues": issues,
        "invalid_ohlcv_rows": int(bad.sum()),
        "gaps": gaps,
        "identical_ohlcv_rows": int(values.duplicated().sum()),
        "identical_values_note": "Equal OHLCV at different timestamps is not removed.",
    }


def parse(payload, timeframe):
    raw = pd.read_csv(io.BytesIO(payload), header=None)
    if raw.empty or raw.shape[1] != 12:
        raise ValueError("Expected 12-column Binance klines")
    unit = "us" if raw.iloc[0, 0] > 10**14 else "ms"
    index = pd.DatetimeIndex(pd.to_datetime(raw[0], unit=unit, utc=True), name="open_time")
    closes = pd.DatetimeIndex(pd.to_datetime(raw[6], unit=unit, utc=True))
    valid = (closes >= index) & (closes < index + pd.Timedelta(hours=HOURS[timeframe]))
    frame = raw.iloc[:, 1:6].astype(float)
    frame.columns = COLUMNS
    frame.index = index
    valid &= index == index.floor(timeframe)
    rejected = [str(t) for t in index[~valid]]
    frame = frame.loc[valid].copy()
    frame.attrs["quarantined_source_timestamps"] = rejected
    return frame


def pages(start, end):
    """Monthly pagination plus completed daily archives for the final partial month."""
    cursor = pd.Timestamp(start)
    end = pd.Timestamp(end)
    while cursor < end:
        following = cursor + pd.offsets.MonthBegin(1)
        if cursor.day == 1 and following <= end:
            yield "monthly", cursor.strftime("%Y-%m"), cursor, following
            cursor = following
        else:
            following = min(cursor + pd.Timedelta(days=1), end)
            yield "daily", cursor.strftime("%Y-%m-%d"), cursor, following
            cursor = following


def download_one(root, asset, timeframe, start, end, fetch=fetch_bytes):
    directory = root / asset / timeframe
    directory.mkdir(parents=True, exist_ok=True)
    frames, sources, errors = [], [], []
    for cadence, stamp, left, right in pages(start, end):
        name = f"{asset}-{timeframe}-{stamp}"
        url = (
            f"https://data.binance.vision/data/spot/{cadence}/klines/{asset}/{timeframe}/{name}.zip"
        )
        checkpoint = directory / "pages" / (name + ".json")
        try:
            if checkpoint.exists():
                source = json.loads(checkpoint.read_text(encoding="utf-8"))
                payload = (directory / "raw" / (source["sha256"] + ".zip")).read_bytes()
                if source["url"] != url or hashlib.sha256(payload).hexdigest() != source["sha256"]:
                    raise ValueError("Corrupt checkpoint or source identity")
            else:
                payload = fetch(url)
                checksum = fetch(url + ".CHECKSUM").decode("ascii").split()
                sha = hashlib.sha256(payload).hexdigest()
                if checksum != [sha, name + ".zip"]:
                    raise ValueError("SHA256 checksum mismatch")
                source = {"url": url, "sha256": sha, "downloaded_at": datetime.now(UTC).isoformat()}
                retain_bytes(directory / "raw" / (sha + ".zip"), payload)
                retain_bytes(checkpoint, json.dumps(source, sort_keys=True).encode())
            frame = parse(archive_csv(payload, name + ".csv"), timeframe)
            source = source | {
                "quarantined_source_timestamps": frame.attrs.get(
                    "quarantined_source_timestamps", []
                )
            }
            quality = audit(frame, asset, timeframe, left, right)
            if quality["status"] == "INVALID":
                raise ValueError(str(quality))
            frame.attrs = {}
            frames.append(frame)
            sources.append(source)
        except (RuntimeError, ValueError, OSError) as exc:
            error = {"url": url, "error": str(exc), "time": datetime.now(UTC).isoformat()}
            errors.append(error)
            with (directory / "errors.jsonl").open("a", encoding="utf-8") as out:
                out.write(json.dumps(error) + "\n")
    if not frames:
        raise ValueError(f"No reliable archives: {asset}/{timeframe}")
    frame = pd.concat(frames).sort_index()
    quality = audit(frame, asset, timeframe, start, end)
    if quality["status"] == "INVALID":
        raise ValueError(str(quality))
    target = directory / quality["hash"]
    target.mkdir(exist_ok=True)
    parquet = target / "candles.parquet"
    if parquet.exists():
        if digest(pd.read_parquet(parquet), asset, timeframe) != quality["hash"]:
            raise ValueError("Existing immutable dataset corrupted")
    else:
        frame.to_parquet(parquet)
    manifest = {
        "audit": quality,
        "sources": sources,
        "errors": errors,
        "parquet_sha256": hashlib.sha256(parquet.read_bytes()).hexdigest(),
    }
    path = target / "manifest.json"
    if not path.exists():
        retain_bytes(path, json.dumps(manifest, indent=2).encode())
    print(f"DATA {asset} {timeframe}: {len(frame)} {quality['status']}", flush=True)
    return str(target)


def aggregate_check(hourly, direct, timeframe):
    count = HOURS[timeframe]
    groups = hourly.resample(timeframe)
    aggregated = groups.agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    aggregated = aggregated.loc[groups.size() == count]
    common = aggregated.index.intersection(direct.index)
    a, b = aggregated.loc[common], direct.loc[common]
    # Binance decimal volumes are parsed as float64: tolerate only summation roundoff.
    equal = np.isclose(a, b, rtol=1e-12, atol=1e-8)
    bad = ~equal.all(axis=1)
    return {
        "timeframe": timeframe,
        "compared_bars": len(common),
        "mismatches": int(bad.sum()),
        "max_absolute_difference": (a - b).abs().max().to_dict(),
        "mismatch_samples": [str(t) for t in common[bad][:20]],
        "mismatch_days": sorted({str(t.floor("D")) for t in common[bad]}),
        "tolerance": "rtol=1e-12, atol=1e-8 solely float64 decimal summation roundoff",
        "status": "PASS" if len(common) and not bad.any() else "FAIL",
    }


def download_all(root, start, end):
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = [
            pool.submit(download_one, root, asset, tf, start, end)
            for asset in ("BTCUSDT", "ETHUSDT")
            for tf in HOURS
        ]
        return [job.result() for job in jobs]
