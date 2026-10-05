"""Explicit offline snapshots of USD-M prices, mark and observed funding."""

import hashlib
import json
from pathlib import Path

import pandas as pd

from quant_lab.futures_data import validate_funding
from quant_lab.mtf_data import quarter_audit
from quant_lab.mtf_features import complete_bars
from quant_lab.study_data import audit, digest

QUARTERS = {
    "BTCUSDT": "0a6032afe6c1e90ece9fe7f09ad8e7630860343b8433ca7f0d720102b54ffa97",
    "ETHUSDT": "9d4bcb5a0627a70513522de8d967c52697af68220dba52ce626a9915730e35c8",
}
FUNDING = {
    "BTCUSDT": "15081b49ea5344c1fdab3cb359d7573af092effe14f6fcb513022c13a8f94b89",
    "ETHUSDT": "77ad864037ceb80c61b5352c13d44bae3e22f906f98fe2b4fbce78004771761b",
}
MARK = {
    "BTCUSDT": "e09945f9f4af3acb99be15a7434db30c0f07d7e790912e6a36ead16be50885d6",
    "ETHUSDT": "5ac1d3741f984dc9dea0048dcdddf85876937d9c16ea9eb9ea8537b9c70c2752",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source(root, asset, kind, tf, identity):
    path = root / "data/batch_006_perpetual" / asset / kind / tf / identity
    meta = json.loads((path / "manifest.json").read_text())
    if tuple(
        meta[k] for k in ("exchange", "market_type", "asset", "kind", "timeframe", "hash")
    ) != ("binance", "USD_M_PERPETUAL", asset, kind, tf, identity):
        raise ValueError("Pinned perpetual source identity mismatch")
    if sha(path / "data.parquet") != meta["parquet_sha256"]:
        raise ValueError("Source checksum mismatch")
    f = pd.read_parquet(path / "data.parquet")
    body = f.to_json(date_format="iso", double_precision=15).encode()
    if (
        hashlib.sha256(f"USD_M_PERPETUAL/{asset}/{kind}/{tf}".encode() + body).hexdigest()
        != identity
    ):
        raise ValueError("Source fingerprint mismatch")
    return f, {
        "dataset_id": identity,
        "manifest_sha256": sha(path / "manifest.json"),
        "parquet_sha256": meta["parquet_sha256"],
    }


def observed_funding(root, asset):
    f, meta = source(root, asset, "fundingRate", "events", FUNDING[asset])
    records = []
    hashes = {}
    for path in sorted((root / "data/batch_006_perpetual" / asset / "funding_rest").glob("*.json")):
        if path.name.startswith("error"):
            continue
        rows = json.loads(path.read_text())
        if not isinstance(rows, list) or any(r["symbol"] != asset for r in rows):
            raise ValueError("REST funding identity mismatch")
        records.extend(rows)
        hashes[path.name] = sha(path)
    if records:
        raw = pd.DataFrame(records)
        if (raw.groupby("fundingTime").fundingRate.nunique() > 1).any():
            raise ValueError("Conflicting retained funding")
        raw = raw.drop_duplicates("fundingTime").sort_values("fundingTime")
        tail = pd.DataFrame(
            {"rate": raw.fundingRate.astype(float).to_numpy(), "interval_hours": 8.0},
            index=pd.DatetimeIndex(
                pd.to_datetime(raw.fundingTime, unit="ms", utc=True), name="funding_time"
            ),
        )
        overlap = tail.index.floor("h").isin(f.index.floor("h"))
        archived = f.rate.copy()
        archived.index = archived.index.floor("h")
        for t, v in tail.rate.loc[overlap].items():
            if abs(float(archived.loc[t.floor("h")]) - v) > 1e-15:
                raise ValueError("Archive/REST funding conflict")
        f = pd.concat([f, tail.loc[tail.index > f.index[-1]]])
    validate_funding(f)
    offsets = (f.index - f.index.floor("h")).total_seconds()
    if (offsets >= 1).any() or f.index.floor("h").duplicated().any():
        raise ValueError("Funding timestamps need finer execution")
    hours = f.index.floor("h")
    if not hours.hour.isin([0, 8, 16]).all() or not f.interval_hours.eq(8).all():
        raise ValueError("V1 requires observed 8h settlements at00/08/16 UTC")
    meta["rest_sha256"] = hashes
    return f, meta


def write_bundle(root, asset, tf, frame, origin):
    quality = audit(frame, asset, tf)
    if quality["status"] != "VALID":
        raise ValueError(f"Price bundle not continuous: {quality}")
    target = root / "data/literature_v1/prices" / asset / tf / quality["hash"]
    metadata = {"audit": quality, "source_market": "USD_M_PERPETUAL_PRICES", "source": origin}
    if target.exists():
        current = json.loads((target / "manifest.json").read_text())
        if (
            any(current.get(k) != v for k, v in metadata.items())
            or sha(target / "candles.parquet") != current["parquet_sha256"]
        ):
            raise ValueError("Existing literature bundle changed; no overwrite")
        return target
    target.mkdir(parents=True, exist_ok=False)
    frame.to_parquet(target / "candles.parquet")
    metadata["parquet_sha256"] = sha(target / "candles.parquet")
    (target / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return target


def prepare(root):
    inventory = {}
    for asset, identity in QUARTERS.items():
        directory = root / "data/mtf_15m" / asset / "klines"
        meta = json.loads((directory / "manifest.json").read_text())
        if meta["audit"]["hash"] != identity or sha(directory / "data.parquet") != meta["sha256"]:
            raise ValueError("Pinned quarter source changed")
        quarters = pd.read_parquet(directory / "data.parquet")
        quality = quarter_audit(quarters, asset)
        if quality["hash"] != identity or quality["status"] != "VALID":
            raise ValueError("Invalid quarter source")
        origin = {
            "dataset_id": identity,
            "parquet_sha256": meta["sha256"],
            "manifest_sha256": sha(directory / "manifest.json"),
            "resampling": "complete UTC bars only",
        }
        prices = {
            tf: write_bundle(root, asset, tf, complete_bars(quarters, "15m", tf), origin)
            for tf in ("1h", "4h", "1d")
        }
        funding, funding_meta = observed_funding(root, asset)
        mark, mark_meta = source(root, asset, "markPriceKlines", "1h", MARK[asset])
        mark_audit = audit(mark, asset, "1h")
        if mark_audit["status"] == "INVALID":
            raise ValueError("Invalid mark prices")
        fund_body = funding.to_json(date_format="iso", double_precision=15)
        mark_id = digest(mark, asset, "1h")
        aux_id = hashlib.sha256(
            (
                asset
                + fund_body
                + mark_id
                + json.dumps({"funding": funding_meta, "mark": mark_meta}, sort_keys=True)
            ).encode()
        ).hexdigest()
        target = root / "data/literature_v1/perpetual" / asset / aux_id
        if not target.exists():
            target.mkdir(parents=True, exist_ok=False)
            funding.to_parquet(target / "funding.parquet")
            mark.to_parquet(target / "mark.parquet")
            available = funding.index.floor("h")
            counts = pd.Series(1, index=available).groupby(available.floor("D")).sum()
            days = pd.date_range(available[0].floor("D"), available[-1].floor("D"), freq="D")
            missing = []
            events = set(available)
            for day in days:
                missing.extend(
                    str(day + pd.Timedelta(hours=h))
                    for h in (0, 8, 16)
                    if day + pd.Timedelta(hours=h) not in events
                )
            document = {
                "dataset_id": aux_id,
                "symbol": asset,
                "source_funding": funding_meta,
                "source_mark": mark_meta,
                "funding_sha256": sha(target / "funding.parquet"),
                "mark_sha256": sha(target / "mark.parquet"),
                "funding_start": str(funding.index[0]),
                "funding_end": str(funding.index[-1]),
                "funding_events": len(funding),
                "interval_hours": 8,
                "offset_seconds_max": float((funding.index - available).total_seconds().max()),
                "missing_settlements": missing,
                "incomplete_funding_days": len(days) - int(counts.eq(3).sum()),
                "mark_audit": mark_audit,
                "policy": "actual timestamps; observed settlement rates; "
                "availability assumed at settlement; publication latency unknown; no zero fill",
            }
            (target / "manifest.json").write_text(
                json.dumps(document, indent=2) + "\n", encoding="utf-8"
            )
        load_aux(
            {
                "path": str(target),
                "dataset_id": aux_id,
                "manifest": json.loads((target / "manifest.json").read_text()),
            }
        )
        inventory[asset] = {
            "prices": {tf: str(p.relative_to(root)).replace("\\", "/") for tf, p in prices.items()},
            "perpetual": str(target.relative_to(root)).replace("\\", "/"),
            "perpetual_id": aux_id,
        }
    return inventory


def inspect_aux(base, market):
    if market.perpetual_data is None:
        raise ValueError("Observed funding and mark snapshot required")
    path = (base / market.perpetual_data.dataset).resolve()
    meta = json.loads((path / "manifest.json").read_text())
    if (meta["symbol"], meta["dataset_id"], path.name) != (
        market.symbol,
        market.perpetual_data.dataset_id,
        market.perpetual_data.dataset_id,
    ):
        raise ValueError("Perpetual snapshot identity mismatch")
    return {"path": str(path), "dataset_id": meta["dataset_id"], "manifest": meta}


def load_aux(info):
    path = Path(info["path"])
    meta = info["manifest"]
    for name in ("funding", "mark"):
        if sha(path / f"{name}.parquet") != meta[f"{name}_sha256"]:
            raise ValueError("Perpetual snapshot checksum mismatch")
    funding = pd.read_parquet(path / "funding.parquet")
    mark = pd.read_parquet(path / "mark.parquet")
    validate_funding(funding)
    body = funding.to_json(date_format="iso", double_precision=15)
    identity = hashlib.sha256(
        (
            meta["symbol"]
            + body
            + digest(mark, meta["symbol"], "1h")
            + json.dumps(
                {"funding": meta["source_funding"], "mark": meta["source_mark"]}, sort_keys=True
            )
        ).encode()
    ).hexdigest()
    if identity != meta["dataset_id"]:
        raise ValueError("Perpetual snapshot fingerprint mismatch")
    if audit(mark, meta["symbol"], "1h")["status"] == "INVALID":
        raise ValueError("Invalid mark")
    return {"funding": funding, "mark": mark}


def complete_days(aux):
    fund_hours = aux["funding"].index.floor("h")
    offsets = (aux["funding"].index - fund_hours).total_seconds()
    if (
        (offsets >= 1).any()
        or fund_hours.duplicated().any()
        or not fund_hours.hour.isin([0, 8, 16]).all()
    ):
        raise ValueError("Unsupported settlement clock")
    counts = pd.Series(1, index=fund_hours).groupby(fund_hours.floor("D")).sum()
    mark = aux["mark"]
    marks = mark.groupby(mark.index.floor("D")).size()
    return counts.index[counts == 3].intersection(marks.index[marks == 24])
