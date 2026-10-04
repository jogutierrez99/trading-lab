"""Read-only reconstruction from a consistent journal snapshot or immutable CSV copies."""

import argparse
import csv
import hashlib
import io
import json
import sqlite3
from dataclasses import fields
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pandas as pd

from quant_lab.brokers.instruments import Instrument
from quant_lab.config import CostsConfig
from quant_lab.forward.shadow import ShadowTracker, validate_bar
from quant_lab.forward.shadow_reporting import render
from quant_lab.forward.store import identity
from quant_lab.market_data.okx import Bar

ROOT = Path(__file__).resolve().parents[3]


def snapshot(session_path):
    database = session_path.parent / "forward.sqlite"
    if database.exists():
        with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            found = db.execute(
                "SELECT data FROM sessions WHERE id=?", (session_path.name,)
            ).fetchone()
            if not found:
                raise ValueError("Session absent from journal")
            meta = json.loads(found[0])
            last = db.execute(
                "SELECT max(rowid) FROM events WHERE session=?", (session_path.name,)
            ).fetchone()[0]
            events = [
                json.loads(r[1]) | {"recorded_session": r[0]}
                for r in db.execute(
                    "SELECT session,data FROM events WHERE stream=? AND rowid<=? ORDER BY rowid",
                    (meta["stream_id"], last or 0),
                )
            ]
            intents = [e for e in events if e["kind"] == "ORDER_INTENT_CREATED"]
            gaps = [e for e in events if e["kind"] == "DATA_GAP" and not e.get("resolved", False)]
            return (
                meta,
                intents,
                [e for e in events if e["kind"] == "SIGNAL_GENERATED"],
                [e for e in events if e["kind"] == "MARKET_BAR_CLOSED"],
                gaps,
                "sqlite_readonly_snapshot",
            )
    names = ["session.json", "order_intents.csv", "signals.csv", "bars.csv", "data_gaps.csv"]
    blobs = {
        name: (session_path / name).read_bytes() for name in names if (session_path / name).exists()
    }
    if any((session_path / name).read_bytes() != data for name, data in blobs.items()):
        raise ValueError("CSV exports changed during read; retry or use journal snapshot")

    def rows(name):
        return list(csv.DictReader(io.StringIO(blobs.get(name, b"").decode("utf-8-sig"))))

    gaps = [g for g in rows("data_gaps.csv") if g.get("resolved", "").lower() not in {"true", "1"}]
    return (
        json.loads(blobs["session.json"]),
        rows("order_intents.csv"),
        rows("signals.csv"),
        rows("bars.csv"),
        gaps,
        "csv_snapshot",
    )


def reconstruct(session_path, output_root):
    session_path = Path(session_path).resolve()
    meta, intents, signals, raw_bars, gaps, source = snapshot(session_path)
    cfg = meta["config"]
    tracker = ShadowTracker(
        CostsConfig.model_validate(cfg["inherited"]["costs"]["base"]),
        cfg["inherited"]["risk"]["max_holding_bars"],
    )
    instruments = {}
    for key, raw in cfg["instruments"].items():
        values = raw.copy()
        for name in ("contract_size", "lot_size", "min_size", "tick_size", "max_leverage"):
            values[name] = Decimal(str(values[name]))
        instruments[key] = Instrument(**values)
    warnings = []
    if source == "csv_snapshot":
        warnings.append(
            "Session-only CSV may omit positions carried from prior sessions; "
            "use the journal for full stream reconstruction"
        )
    for intent in intents:
        if not intent.get("id"):
            continue
        matching = [
            s for s in signals if identity(s["signal_id"], intent["strategy"]) == intent["id"]
        ]
        signal = matching[0] if len(matching) == 1 else None
        if signal is None:
            warnings.append("Missing signal link for " + intent["id"] + "; no inferred pairing")
        tracker.open(
            intent,
            instruments[intent["instrument_id"]],
            intent.get("recorded_session", meta["session_id"]),
            signal["signal_id"] if signal else None,
            signal["timestamp"] if signal else None,
        )
    unique = {}
    for raw in raw_bars:
        if not raw.get("instrument_id"):
            continue
        values = {f.name: raw[f.name] for f in fields(Bar)}
        values["timestamp"] = pd.Timestamp(values["timestamp"])
        for k in ("open", "high", "low", "close", "volume"):
            values[k] = float(values[k])
        bar = Bar(**values)
        validate_bar(bar)
        if bar.key in unique and unique[bar.key] != bar:
            raise ValueError("Conflicting reconstruction candle")
        unique[bar.key] = bar
    bars = sorted(
        unique.values(),
        key=lambda b: (b.close_time, b.timeframe, b.instrument_id),
    )
    for bar in bars:
        tracker.update(bar)
    if gaps:
        warnings.append(
            "Unresolved DATA_GAP: committed bars only; "
            "no staging/monitoring bars used; open state is stale"
        )
        for p in tracker.positions.values():
            if p["status"] == "OPEN" and p["coverage"] == "CONTINUOUS":
                p["coverage"] = "DATA_GAP"
    for p in tracker.positions.values():
        if not p["last_bar"] and p["coverage"] == "CONTINUOUS":
            p["coverage"] = "NO_POST_ENTRY_BARS"
        if p["coverage"] != "CONTINUOUS":
            warnings.append(
                p["shadow_position_id"]
                + ": "
                + p["coverage"]
                + "; status and PnL not certified beyond last observation"
            )
    output_root = Path(output_root).resolve()
    if output_root == session_path or session_path in output_root.parents:
        raise ValueError("Derived output must be outside original session")
    out = (
        output_root
        / session_path.name
        / (pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    )
    out.mkdir(parents=True, exist_ok=False)
    payload = dict(
        session=meta, intents=intents, signals=signals, bars=raw_bars, gaps=gaps, source=source
    )
    encoded = json.dumps(payload, sort_keys=True, default=str).encode()
    (out / "source_snapshot.json").write_bytes(encoded)
    (out / "provenance.json").write_text(
        json.dumps(
            dict(
                source_session=str(session_path),
                source_sha256=hashlib.sha256(encoded).hexdigest(),
                warnings=warnings,
            ),
            indent=2,
        ),
        encoding="utf-8",
    )
    report = render(out, tracker.positions, reconstructed=True)
    report += "\n## Reconstruction limits\n\n" + json.dumps(warnings) + "\n"
    (out / "shadow_pnl_summary.md").write_text(report, encoding="utf-8")
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", help="Session ID or directory")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/shadow-pnl")
    args = parser.parse_args(argv)
    path = Path(args.session)
    if not path.is_dir():
        path = ROOT / "results/forward" / args.session
    try:
        print(reconstruct(path, args.output))
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
