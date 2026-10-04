"""Offline conversion of pinned USD-M 1h prices to an ordinary lab bundle.

No downloads, resampling, filtering, funding fabrication or backtests.
"""

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from quant_lab.study_data import audit

SOURCES = {
    "ETHUSDT": "a65b55a9ad440549555274cbccc1f87bfcd27ed1832a118ad8c488f8eaacfa90",
    "BTCUSDT": "d68f6667bc96d9ee7d925e48e563e06c53e284db890c098cf5da4b9f655ceba6",
}


def prepare(root: Path, asset: str, output: Path | None = None) -> Path:
    source = root / "data/batch_006_perpetual" / asset / "klines/1h" / SOURCES[asset]
    payload = (source / "manifest.json").read_bytes()
    manifest = json.loads(payload)
    expected = ("binance", "USD_M_PERPETUAL", asset, "klines", "1h", SOURCES[asset])
    keys = ("exchange", "market_type", "asset", "kind", "timeframe", "hash")
    if tuple(manifest[k] for k in keys) != expected:
        raise ValueError("Pinned source identity mismatch")
    parquet = source / "data.parquet"
    if hashlib.sha256(parquet.read_bytes()).hexdigest() != manifest["parquet_sha256"]:
        raise ValueError("Source SHA256 mismatch")
    frame = pd.read_parquet(parquet)
    # Gaps are allowed, sub-hour observations are not native hourly bars.
    if (
        not isinstance(frame.index, pd.DatetimeIndex)
        or str(frame.index.tz) != "UTC"
        or not frame.index.is_monotonic_increasing
        or not frame.index.is_unique
        or (frame.index != frame.index.floor("h")).any()
    ):
        raise ValueError("Native 1h prices require sorted unique hourly UTC timestamps")
    body = frame.to_json(date_format="iso", double_precision=15).encode()
    fingerprint = hashlib.sha256(f"USD_M_PERPETUAL/{asset}/klines/1h".encode() + body).hexdigest()
    if fingerprint != SOURCES[asset]:
        raise ValueError("Source fingerprint mismatch")
    if (str(frame.index[0]), str(frame.index[-1]), len(frame)) != (
        manifest["start"],
        manifest["end"],
        manifest["rows"],
    ):
        raise ValueError("Source coverage mismatch")
    quality = audit(frame, asset, "1h")
    if quality["status"] == "INVALID":
        raise ValueError(f"Invalid source: {quality}")
    target = (output or root / "data/lab_1h_prices") / asset / quality["hash"]
    metadata = {
        "audit": quality,
        "source_market": "USD_M_PERPETUAL_PRICES",
        "execution_note": "synthetic; funding not modelled; no liquidations",
        "source_dataset_id": SOURCES[asset],
        "source_manifest_sha256": hashlib.sha256(payload).hexdigest(),
        "source_parquet_sha256": manifest["parquet_sha256"],
    }
    if target.exists():
        current = json.loads((target / "manifest.json").read_text())
        if any(current.get(k) != v for k, v in metadata.items()):
            raise ValueError("Existing bundle provenance mismatch; refusing overwrite")
        data = target / "candles.parquet"
        if hashlib.sha256(data.read_bytes()).hexdigest() != current["parquet_sha256"]:
            raise ValueError("Existing bundle SHA256 mismatch")
        pd.testing.assert_frame_equal(pd.read_parquet(data), frame)
        return target
    target.mkdir(parents=True, exist_ok=False)
    frame.to_parquet(target / "candles.parquet")
    metadata["parquet_sha256"] = hashlib.sha256(
        (target / "candles.parquet").read_bytes()
    ).hexdigest()
    (target / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset", choices=tuple(SOURCES))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(prepare(args.root.resolve(), args.asset))
