import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from quant_lab.binance_history import download_history
from quant_lab.csv_history import load_csv_history
from quant_lab.history import HistoryRequest
from quant_lab.history_cache import read_bundle


def export(tmp_path, mutation=None):
    request = HistoryRequest(
        start=pd.Timestamp("2025-01-01T00:00:00Z").to_pydatetime(),
        end=pd.Timestamp("2025-02-01T00:00:00Z").to_pydatetime(),
        warmup_bars=200,
    )
    responses = {}
    for month, end, unit in [("2024-12", "2025-01-01", "ms"), ("2025-01", "2025-02-01", "us")]:
        index = pd.date_range(month + "-01", end, freq="h", inclusive="left", tz="UTC")
        if month == "2024-12":
            if mutation == "gap":
                index = index.delete(-4)
            elif mutation == "duplicate":
                index = index.insert(2, index[1])
            elif mutation == "order":
                index = index[::-1]
        tick = 3600000 if unit == "ms" else 3600000000
        lines = [
            f"{t},100,110,90,105,1,{t + tick - 1},100,1,1,1,0" for t in index.as_unit(unit).asi8
        ]
        if month == "2024-12" and mutation in ("bounds", "nan"):
            # Corruption outside the requested warmup still invalidates the full source month.
            lines[0] = lines[0].replace(
                ",110,90,105,", ",95,90,105," if mutation == "bounds" else ",110,90,NaN,"
            )
        name = f"BTCUSDT-1h-{month}"
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr(name + ".csv", "\n".join(lines))
        payload = stream.getvalue()
        responses[name + ".zip"] = payload
        responses[name + ".zip.CHECKSUM"] = (
            f"{hashlib.sha256(payload).hexdigest()} {name}.zip".encode()
        )
    try:
        download_history(
            request, lambda url: responses[url.rsplit("/", 1)[1]], csv_dir=tmp_path / "csv"
        )
    except ValueError:
        if mutation is None:
            raise
    manifest = next((tmp_path / "csv").glob("manifest-*.json"))
    return request, manifest


def test_subset_cli_excludes_invalid_source_month_without_changing_parent(tmp_path, repo_root):
    request, manifest = export(tmp_path, mutation="gap")
    original = manifest.read_bytes()
    config = tmp_path / "subset.yaml"
    config.write_text("start: 2025-01-01T00:00:00Z\nend: 2025-02-01T00:00:00Z\nwarmup_bars: 0\n")
    command = [
        sys.executable,
        str(repo_root / "scripts/prepare_history_subset.py"),
        "--config",
        str(config),
        "--audit",
        str(manifest),
        "--csv-dir",
        str(tmp_path / "csv"),
        "--cache-dir",
        str(tmp_path / "cache"),
        "--report-dir",
        str(tmp_path / "reports"),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    event = json.loads(result.stdout)
    assert event["rows"] == 744
    assert manifest.read_bytes() == original
    frame = read_bundle(Path(event["bundle"]), request.model_copy(update={"warmup_bars": 0}))
    assert len(frame) == 744


def run_cli(tmp_path, repo_root, manifest):
    config = tmp_path / "history.yaml"
    config.write_text("start: 2025-01-01T00:00:00Z\nend: 2025-02-01T00:00:00Z\nwarmup_bars: 200\n")
    return subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/import_csv.py"),
            "--config",
            str(config),
            "--manifest",
            str(manifest),
            "--csv-dir",
            str(tmp_path / "csv"),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--report-dir",
            str(tmp_path / "reports"),
        ],
        capture_output=True,
        text=True,
    )


def test_csv_cli_roundtrip_units_warmup_and_reuse(tmp_path, repo_root):
    request, manifest = export(tmp_path)
    result = run_cli(tmp_path, repo_root, manifest)
    assert result.returncode == 0, result.stderr
    event = json.loads(result.stdout)
    assert event["rows"] == 944
    bundle = Path(event["path"])
    before = (bundle / "manifest.json").read_bytes()
    frame = read_bundle(bundle, request)
    assert frame.index[0] == pd.Timestamp("2024-12-23T16:00:00Z")
    assert (frame.close == 105).all()
    assert run_cli(tmp_path, repo_root, manifest).returncode == 0
    assert (bundle / "manifest.json").read_bytes() == before
    assert len(list((tmp_path / "reports").glob("*.json"))) == 1


@pytest.mark.parametrize("mutation", ["gap", "duplicate", "order", "bounds", "nan"])
def test_csv_cli_rejects_invalid_sources_without_bundle(tmp_path, repo_root, mutation):
    request, manifest = export(tmp_path, mutation)
    result = run_cli(tmp_path, repo_root, manifest)
    assert result.returncode == 1
    assert json.loads(result.stderr)["event"] == "csv_import_failed"
    assert not list((tmp_path / "cache").rglob("*.parquet"))
    report = json.loads(next((tmp_path / "reports").glob("*.json")).read_text())
    assert report["status"] == "rejected"
    assert len(report["checked"]) == 2  # Audits later months after an earlier failure.
    assert len(report["issues"]) == 1


@pytest.mark.parametrize(
    "mutation", ["checksum", "missing_file", "missing_month", "duplicate_source", "path", "request"]
)
def test_csv_integrity_and_manifest_rejection(tmp_path, mutation):
    request, manifest = export(tmp_path)
    data = json.loads(manifest.read_text())
    csv = next((tmp_path / "csv").rglob("*.csv"))
    if mutation == "checksum":
        csv.write_bytes(csv.read_bytes().replace(b",105,", b",104,", 1))
    elif mutation == "missing_file":
        csv.unlink()
    elif mutation == "missing_month":
        data["sources"].pop()
    elif mutation == "duplicate_source":
        data["sources"].append(data["sources"][0])
    elif mutation == "path":
        data["sources"][0]["sha256"] = "../../outside"
    else:
        data["request"]["warmup_bars"] = 0
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_csv_history(request, manifest, tmp_path / "csv", tmp_path / "reports")
