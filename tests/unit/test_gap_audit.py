import hashlib
import io
import json
import zipfile

import pandas as pd
import pytest

from quant_lab.gap_audit import assess_rows, audit_hours

HOUR = pd.Timestamp("2021-02-11T04:00:00Z")


def minute_rows():
    start = HOUR.value // 1000000
    return [
        [t, "100", "110", "90", "105", "1", t + 59999, "1", 1, "1", "1", "0"]
        for t in range(start, start + 3600000, 60000)
    ]


def test_complete_minutes_aggregate_exactly():
    result = assess_rows(minute_rows(), HOUR, "1m")
    assert result["status"] == "complete"
    assert result["candidate_ohlcv"] == ["100", "110", "90", "105", "60"]


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "order", "bounds", "nan", "close"])
def test_no_candidate_from_bad_minutes(mutation):
    rows = minute_rows()
    if mutation == "missing":
        rows.pop(12)
    elif mutation == "duplicate":
        rows[1] = rows[0]
    elif mutation == "order":
        rows.reverse()
    elif mutation == "bounds":
        rows[0][2] = "95"
    elif mutation == "nan":
        rows[0][5] = "NaN"
    else:
        rows[0][6] += 1
    result = assess_rows(rows, HOUR, "1m")
    assert result["status"] in ("incomplete", "invalid")
    assert "candidate_ohlcv" not in result


@pytest.mark.parametrize(
    "mode", ["absent", "complete", "conflict", "network_error", "bad_checksum"]
)
def test_audit_sources_and_evidence(tmp_path, mode):
    def fetch(url):
        if mode == "network_error":
            raise RuntimeError("network unavailable")
        if "/api/v3/" in url:
            rows = (
                minute_rows() if mode in ("complete", "conflict") and "interval=1m" in url else []
            )
            if rows and mode == "conflict":
                rows[0][5] = "2"
            return json.dumps(rows).encode()
        name = url.rsplit("/", 1)[1].removesuffix(".CHECKSUM").removesuffix(".zip")
        rows = minute_rows() if mode in ("complete", "conflict") and "-1m-" in name else []
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr(
                zipfile.ZipInfo(name + ".csv"), "\n".join(",".join(map(str, row)) for row in rows)
            )
        payload = stream.getvalue()
        if url.endswith(".CHECKSUM"):
            digest = "bad" if mode == "bad_checksum" else hashlib.sha256(payload).hexdigest()
            return f"{digest} {name}.zip".encode()
        return payload

    path = audit_hours([HOUR.isoformat()], tmp_path, fetch)
    report = json.loads(path.read_text())
    item = report["results"][0]
    assert item["status"] == {"complete": "candidate", "conflict": "conflicting_candidates"}.get(
        mode, "unresolved"
    )
    assert len(item["checks"]) == 4
    for check in item["checks"].values():
        for source in check["sources"]:
            payload = (tmp_path / "evidence" / source["sha256"]).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == source["sha256"]
    if mode == "network_error":
        assert all(check["status"] == "error" for check in item["checks"].values())
    if mode == "bad_checksum":
        assert item["checks"]["daily_1h"]["status"] == "error"
    assert not list(tmp_path.rglob("*.parquet"))
