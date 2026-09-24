import hashlib
import io
import json
import subprocess
import sys
import zipfile
from datetime import UTC, datetime

import pandas as pd
import pytest

from quant_lab.binance_history import download_history, parse_archive
from quant_lab.candles import validate_candles
from quant_lab.history import HistoryRequest
from quant_lab.history_cache import find_bundle, read_bundle, save_bundle


def request_for(start="2024-01-01", end="2024-02-01", warmup=0):
    return HistoryRequest(
        start=pd.Timestamp(start, tz="UTC").to_pydatetime(),
        end=pd.Timestamp(end, tz="UTC").to_pydatetime(),
        warmup_bars=warmup,
    )


def candles(request):
    index = pd.date_range(
        request.download_start, request.end, freq="h", inclusive="left", name="open_time"
    )
    return pd.DataFrame(
        {"open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 1.0}, index=index
    )


def archive_bytes(frame, name, microseconds=False, early=False):
    unit = "us" if microseconds else "ms"
    tick = 3600000000 if microseconds else 3600000
    lines = []
    for timestamp in frame.index.as_unit(unit).asi8:
        close = timestamp + tick - (5000 if early else 1)
        lines.append(f"{timestamp},100,110,90,105,1,{close},100,1,1,1,0")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(name + ".csv", "\n".join(lines))
    return stream.getvalue()


@pytest.mark.parametrize("year", [2024, 2025])
def test_month_download_and_units(year):
    request = request_for(f"{year}-01-01", f"{year}-02-01")
    expected = candles(request)
    name = f"BTCUSDT-1h-{year}-01"
    payload = archive_bytes(expected, name, year >= 2025)
    calls = []

    def fetch(url):
        calls.append(url)
        if url.endswith(".CHECKSUM"):
            return f"{hashlib.sha256(payload).hexdigest()}  {name}.zip".encode()
        return payload

    actual, sources = download_history(request, fetch)
    pd.testing.assert_frame_equal(actual, expected, check_freq=False)
    assert len(calls) == 2
    assert len(sources) == 1


def test_checksum_failure():
    with pytest.raises(ValueError, match="checksum"):
        download_history(request_for(), lambda url: b"incorrect")


def test_audit_continues_and_retains_rejected_sources(tmp_path):
    request = request_for("2024-01-01", "2024-03-01")
    responses = {}
    for start, end in [("2024-01-01", "2024-02-01"), ("2024-02-01", "2024-03-01")]:
        name = f"BTCUSDT-1h-{start[:7]}"
        frame = candles(request_for(start, end))
        if start.endswith("01-01"):
            frame = frame.drop(frame.index[4])
        payload = archive_bytes(frame, name)
        responses[name + ".zip"] = payload
        responses[name + ".zip.CHECKSUM"] = (
            f"{hashlib.sha256(payload).hexdigest()} {name}.zip".encode()
        )
    with pytest.raises(ValueError, match="Historical data rejected"):
        download_history(request, lambda url: responses[url.rsplit("/", 1)[1]], tmp_path)
    reports = list(tmp_path.glob("quality-*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text())
    assert len(report["sources"]) == 2
    assert len(report["issues"]) == 1
    assert len(list(tmp_path.glob("*.zip"))) == 2
    assert not list(tmp_path.glob("*.parquet"))


@pytest.mark.parametrize("offset", [-1, 3600000])
def test_out_of_hour_close_rejected(offset):
    timestamp = 1704067200000
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("test.csv", f"{timestamp},100,110,90,105,1,{timestamp + offset},1,1,1,1,0")
    with pytest.raises(ValueError, match="close timestamps"):
        parse_archive(stream.getvalue(), "test.csv", False)


def test_warmup_crosses_month_boundary():
    request = request_for("2025-01-01", "2025-01-02", warmup=200)
    sources = {}
    for start, end in [("2024-12-01", "2025-01-01"), ("2025-01-01", "2025-02-01")]:
        name = f"BTCUSDT-1h-{start[:7]}"
        payload = archive_bytes(candles(request_for(start, end)), name, start.startswith("2025"))
        sources[name + ".zip"] = payload
        sources[name + ".zip.CHECKSUM"] = (
            f"{hashlib.sha256(payload).hexdigest()} {name}.zip".encode()
        )
    frame, provenance = download_history(request, lambda url: sources[url.rsplit("/", 1)[1]])
    assert len(frame) == 224
    assert frame.index[0] == pd.Timestamp("2024-12-23T16:00:00Z")
    assert len(provenance) == 2


def test_early_close_recorded_without_early_availability():
    payload = archive_bytes(candles(request_for()), "test", early=True)
    frame = parse_archive(payload, "test.csv", False)
    assert len(frame.attrs["early_source_closes"]) == len(frame)
    validate_candles(frame, request_for())


@pytest.mark.parametrize(
    "mutation",
    [
        "gap",
        "duplicate",
        "order",
        "naive",
        "nan",
        "bounds",
        "negative_volume",
        "zero_price",
        "misaligned",
        "extra",
    ],
)
def test_invalid_candles(mutation):
    request = request_for()
    frame = candles(request)
    if mutation == "gap":
        frame = frame.drop(frame.index[2])
    elif mutation == "duplicate":
        frame = pd.concat([frame, frame.iloc[:1]])
    elif mutation == "order":
        frame = frame.iloc[::-1]
    elif mutation == "naive":
        frame.index = frame.index.tz_localize(None)
    elif mutation == "misaligned":
        frame.index += pd.Timedelta(minutes=1)
    elif mutation == "extra":
        frame["other"] = 1
    else:
        column, value = {
            "nan": ("close", float("nan")),
            "bounds": ("high", 95.0),
            "negative_volume": ("volume", -1.0),
            "zero_price": ("low", 0.0),
        }[mutation]
        frame.loc[frame.index[0], column] = value
    with pytest.raises(ValueError):
        validate_candles(frame, request)


@pytest.mark.parametrize(
    "update",
    [
        {"start": datetime(2024, 1, 1)},
        {"end": datetime(2023, 1, 1, tzinfo=UTC)},
        {"warmup_bars": -1},
        {"timeframe": "5m"},
        {"market_type": "futures"},
        {"unknown": 1},
        {"start": datetime(2024, 1, 1, 0, 1, tzinfo=UTC)},
    ],
)
def test_invalid_request(update):
    with pytest.raises(ValueError):
        HistoryRequest.model_validate(request_for().model_dump() | update)


def test_cache_integrity_revisions_and_cli(tmp_path, repo_root):
    request = request_for()
    frame = candles(request)
    bundle = save_bundle(tmp_path / "cache", frame, request, [])
    before = (bundle / "manifest.json").read_bytes()
    assert save_bundle(tmp_path / "cache", frame, request, []) == bundle
    assert (bundle / "manifest.json").read_bytes() == before
    assert find_bundle(tmp_path / "cache", request) == bundle
    pd.testing.assert_frame_equal(read_bundle(bundle, request), frame, check_freq=False)
    config = tmp_path / "history.yaml"
    config.write_text("start: 2024-01-01T00:00:00Z\nend: 2024-02-01T00:00:00Z\nwarmup_bars: 0\n")
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/download_data.py"),
            "--config",
            str(config),
            "--cache-dir",
            str(tmp_path / "cache"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["event"] == "dataset_ready"
    changed = frame.copy()
    changed.iloc[0, 4] = 2.0
    revision = save_bundle(tmp_path / "cache", changed, request, [])
    assert revision != bundle
    with pytest.raises(ValueError, match="Multiple"):
        find_bundle(tmp_path / "cache", request)
    (bundle / "candles.parquet").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="integrity"):
        read_bundle(bundle, request)
    with pytest.raises(ValueError, match="integrity"):
        save_bundle(tmp_path / "cache", frame, request, [])
