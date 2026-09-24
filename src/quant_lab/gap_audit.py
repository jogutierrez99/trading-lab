"""Read-only corroboration of missing spot hours; never patches a dataset."""

import csv
import hashlib
import io
import json
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd

from quant_lab.binance_history import fetch_bytes, retain_bytes


def assess_rows(rows: list, hour: pd.Timestamp, interval: str) -> dict:
    """Require an exact complete hour, valid OHLCV and interval-local close times."""
    step = 60000 if interval == "1m" else 3600000
    start = hour.value // 1000000
    expected = list(range(start, start + 3600000, step))
    selected = []
    try:
        for row in rows:
            if not isinstance(row, list) or len(row) != 12:
                raise ValueError("Expected 12 Binance kline fields")
            opening = int(row[0])
            if str(opening) != str(row[0]):
                raise ValueError("Expected integer millisecond timestamp")
            if start <= opening < start + 3600000:
                selected.append(row)
        times = [int(row[0]) for row in selected]
        if len(set(times)) != len(times) or times != sorted(times):
            raise ValueError("Duplicate or unsorted timestamps")
        for row in selected:
            opening, closing = int(row[0]), int(row[6])
            if opening % step or not opening <= closing < opening + step:
                raise ValueError("Invalid interval timestamps")
            o, h, low, c, v = [Decimal(str(value)) for value in row[1:6]]
            if not all(value.is_finite() for value in (o, h, low, c, v)):
                raise ValueError("Nonfinite OHLCV")
            if min(o, h, low, c) <= 0 or v < 0 or low > min(o, c) or h < max(o, c):
                raise ValueError("Invalid OHLCV bounds")
        missing = [
            pd.Timestamp(t, unit="ms", tz="UTC").isoformat() for t in expected if t not in times
        ]
        result = {
            "status": "complete" if times == expected else "incomplete",
            "rows": len(selected),
            "expected_rows": len(expected),
            "missing": missing,
        }
        if times == expected:
            result["candidate_ohlcv"] = [
                str(Decimal(str(selected[0][1]))),
                str(max(Decimal(str(row[2])) for row in selected)),
                str(min(Decimal(str(row[3])) for row in selected)),
                str(Decimal(str(selected[-1][4]))),
                str(sum(Decimal(str(row[5])) for row in selected)),
            ]
        return result
    except (ValueError, TypeError, InvalidOperation, OverflowError) as exc:
        return {"status": "invalid", "error": str(exc)}


def audit_hours(
    hours: list[str], output: Path, fetch: Callable[[str], bytes] = fetch_bytes
) -> Path:
    timestamps = [pd.Timestamp(hour) for hour in hours]
    if not timestamps or len(set(timestamps)) != len(timestamps):
        raise ValueError("Provide distinct missing hours")
    for hour in timestamps:
        if str(hour.tz) != "UTC" or hour != hour.floor("h") or hour.year != 2021:
            raise ValueError("This audit supports UTC hourly BTCUSDT spot gaps in 2021 only")
    daily = {}
    results = []

    def capture(url: str) -> tuple[bytes, dict]:
        payload = fetch(url)
        digest = hashlib.sha256(payload).hexdigest()
        retain_bytes(output / "evidence" / digest, payload)
        return payload, {
            "url": url,
            "sha256": digest,
            "retrieved_at": datetime.now(UTC).isoformat(),
        }

    for hour in timestamps:
        checks = {}
        for interval in ("1h", "1m"):
            key = (f"{hour:%Y-%m-%d}", interval)
            if key not in daily:
                name = f"BTCUSDT-{interval}-{key[0]}"
                url = f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/{interval}/{name}.zip"
                evidence = []
                try:
                    payload, source = capture(url)
                    evidence.append(source)
                    checksum, source = capture(url + ".CHECKSUM")
                    evidence.append(source)
                    fields = checksum.decode("ascii").split()
                    if fields != [hashlib.sha256(payload).hexdigest(), name + ".zip"]:
                        raise ValueError("Daily archive checksum mismatch")
                    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                        if archive.namelist() != [name + ".csv"]:
                            raise ValueError("Unexpected daily archive members")
                        rows = list(csv.reader(io.StringIO(archive.read(name + ".csv").decode())))
                    daily[key] = (rows, evidence, None)
                except (ValueError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
                    daily[key] = ([], evidence, str(exc))
            rows, evidence, error = daily[key]
            checks[f"daily_{interval}"] = {
                **(
                    {"status": "error", "error": error}
                    if error
                    else assess_rows(rows, hour, interval)
                ),
                "sources": evidence,
            }
            start = hour.value // 1000000
            query = urlencode(
                {
                    "symbol": "BTCUSDT",
                    "interval": interval,
                    "startTime": start,
                    "endTime": start + 3599999,
                    "limit": 1000,
                }
            )
            url = "https://data-api.binance.vision/api/v3/klines?" + query
            evidence = []
            try:
                payload, source = capture(url)
                evidence.append(source)
                rows = json.loads(payload)
                if not isinstance(rows, list):
                    raise ValueError("Expected API list response")
                check = assess_rows(rows, hour, interval)
                if len(rows) != check.get("rows", len(rows)):
                    check = {
                        "status": "invalid",
                        "error": "API returned rows outside requested hour",
                    }
                checks[f"api_{interval}"] = {**check, "sources": evidence}
            except (ValueError, OSError, RuntimeError) as exc:
                checks[f"api_{interval}"] = {
                    "status": "error",
                    "error": str(exc),
                    "sources": evidence,
                }
        candidates = [
            tuple(Decimal(v) for v in check["candidate_ohlcv"])
            for check in checks.values()
            if "candidate_ohlcv" in check
        ]
        status = "unresolved"
        if candidates:
            status = "candidate" if len(set(candidates)) == 1 else "conflicting_candidates"
        item = {"hour": hour.isoformat(), "status": status, "checks": checks}
        results.append(item)
        print(
            json.dumps(
                {
                    "event": "gap_audited",
                    "hour": item["hour"],
                    "status": status,
                    "rows": {name: check.get("rows") for name, check in checks.items()},
                }
            ),
            flush=True,
        )
    report = {
        "schema_version": 1,
        "symbol": "BTCUSDT",
        "market": "spot",
        "results": results,
        "policy": "Candidates only; no historical data modified. Absence does not prove no trades.",
    }
    body = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    path = output / f"audit-{hashlib.sha256(body).hexdigest()}.json"
    retain_bytes(path, body)
    return path
