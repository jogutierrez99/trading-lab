"""Dedicated user-operated public-data runner. Does not import legacy execution routing."""

import argparse
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

import pandas as pd

from quant_lab.brokers.okx_demo import PUBLIC, OKXDemoBroker
from quant_lab.experiments import provenance
from quant_lab.forward.donchian import DonchianEngine, DonchianStore, inspect
from quant_lab.forward.donchian_config import (
    DEFAULT,
    ROOT,
    execution,
    load,
    resolved,
    select_instrument,
)
from quant_lab.forward.store import encode
from quant_lab.lab_evidence import new_id, sha256
from quant_lab.market_data.okx import DataGap, OKXMarketData, parse_bar


class PublicBroker:
    """Narrow capability: no private endpoints or order transport, even if keys exist."""

    def __init__(self, broker):
        self.broker = broker

    def get(self, endpoint, params=None):
        if endpoint not in PUBLIC:
            raise ValueError("Donchian permits public market reads only")
        return self.broker.get(endpoint, params)

    def server_time(self):
        return int(self.get("/api/v5/public/time")[0]["ts"])

    def get_instruments(self):
        return self.get("/api/v5/public/instruments", {"instType": "FUTURES"})


def code_identity():
    code = provenance(ROOT)
    names = [
        "forward/donchian.py",
        "forward/donchian_config.py",
        "forward/donchian_runner.py",
        "forward/store.py",
        "risk.py",
        "backtest.py",
        "config.py",
        "execution_config.py",
        "market_data/okx.py",
        "brokers/okx_demo.py",
        "brokers/instruments.py",
        "features.py",
        "strategies/base.py",
        "strategies/donchian_atr_breakout.py",
        "strategies/trend_volatility_breakout_v1.py",
        "trend_expansion_features.py",
        "eth_donchian_review.py",
        "lab_eth_short_history.py",
    ]
    files = {n: sha256(ROOT / "src/quant_lab" / n) for n in names}
    code["code_sha256"] = hashlib.sha256(
        encode(dict(files=files, dependencies=code["dependencies"])).encode()
    ).hexdigest()
    code["files"] = files
    return code


def public_preflight(config, context, broker):
    feed = OKXMarketData(broker, [])
    now = feed.now()
    inst, metadata = select_instrument(config, broker, now)
    feed.instruments = [inst.instrument_id]
    bars = feed.history(inst.instrument_id, "1h", config.warmup_bars)
    result = resolved(config, inst, metadata, context)
    return feed, inst, bars, result


def check_receipt(path, config_path, scope, code):
    receipt = json.loads(path.read_text(encoding="utf-8"))
    now = pd.Timestamp.now(tz="UTC")
    stamp = pd.Timestamp(receipt["created_at"])
    if (
        receipt["status"] != "PUBLIC_PREFLIGHT_OK"
        or receipt["config_sha256"] != sha256(config_path)
        or receipt["code_sha256"] != code["code_sha256"]
        or encode(receipt["resolved"]) != encode(scope)
        or stamp.tzinfo is None
        or not pd.Timedelta(0) <= now - stamp <= pd.Timedelta(minutes=30)
    ):
        raise ValueError("Fresh matching public preflight receipt required")


def resume_header(output, session):
    with sqlite3.connect((output / "forward.sqlite").as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute("SELECT data FROM sessions WHERE id=?", (session,)).fetchone()
        if not row:
            raise ValueError("Unknown resume session")
        header = json.loads(row[0])
        if not db.execute(
            "SELECT 1 FROM checkpoints WHERE stream=?", (header["stream_id"],)
        ).fetchone():
            raise ValueError("Session has no recoverable checkpoint")
        return header


def tick(engine, feed):
    now = feed.now()
    if engine.state["gap"]:
        bars = feed.history(
            engine.instrument, "1h", 1000, since=pd.Timestamp(engine.state["last_closed"])
        )
        engine.recover(bars, now)
    raw = feed.broker.get(
        "/api/v5/market/candles", {"instId": engine.instrument, "bar": "1H", "limit": "3"}
    )
    now = feed.now()
    if not raw:
        raise DataGap("No current candle observations")
    stamps = [row[0] for row in raw]
    if len(set(stamps)) != len(stamps):
        raise DataGap("Duplicate current candle timestamps")
    confirmed = [parse_bar(engine.instrument, "1h", row, now) for row in raw]
    for bar in sorted((b for b in confirmed if b), key=lambda b: b.timestamp):
        if bar.timestamp >= pd.Timestamp(engine.state["last_closed"]):
            engine.closed(bar, now)
    if pd.Timestamp(engine.state["last_closed"]) + pd.Timedelta(hours=1) != now.floor("h"):
        raise DataGap("Latest closed signal context unavailable")
    current = [r for r in raw if pd.Timestamp(int(r[0]), unit="ms", tz="UTC") == now.floor("h")]
    if len(current) == 1:
        row = current[0]
        # Validate OHLCV shape/ranges independently; confirm=0 is context OPEN only.
        # No partial high/low/close reaches strategy or protection evaluation.
        opening = float(row[1])
        values = list(map(float, row[1:5]))
        if (
            len(row) != 9
            or row[8] != "0"
            or not all(pd.notna(v) and abs(v) != float("inf") for v in values)
            or min(values) <= 0
            or values[2] > min(values[0], values[3])
            or values[1] < max(values[0], values[3])
        ):
            raise ValueError("Invalid current opening candle")
        if float(row[6]) > 0:
            engine.opening(now.floor("h"), opening, now, volume=float(row[6]))
    with engine.store.db:
        for name in list(engine.state["pending"]):
            if now - pd.Timestamp(engine.state["pending"][name]["close"]) > pd.Timedelta(
                seconds=90
            ):
                engine.missed(name, "opening_not_observed_before_deadline", now)
        engine.checkpoint()


def run(config_path, receipt, resume=None, broker=None):
    config, output, context = load(config_path)
    code = code_identity()
    # Verify the receipt before any network or financial/session writes.
    proof = json.loads(receipt.read_text(encoding="utf-8"))
    check_receipt(receipt, config_path, proof["resolved"], code)
    feed, inst, bars, scope = public_preflight(
        config, context, PublicBroker(broker or OKXDemoBroker())
    )
    check_receipt(receipt, config_path, scope, code)
    header = resume_header(output, resume) if resume else None
    store = DonchianStore(output, scope, code)
    status = "failed"
    try:
        saved = store.restore()
        if saved and not header:
            raise ValueError(
                "Existing accounts require explicit --resume SESSION_ID; no capital reset"
            )
        if header and (header["stream_id"] != store.stream or not saved):
            raise ValueError(
                "Cannot resume changed code/config/instrument; preserve previous positions"
            )
        engine = DonchianEngine(
            store,
            context[1],
            context[2],
            execution(inst, context[3]),
            inst.instrument_id,
            context[0].earliest_signal_close_utc,
            feed.now(),
        )
        if saved:
            last = pd.Timestamp(saved["last_closed"])
            recovered = feed.history(inst.instrument_id, "1h", 1000, since=last)
            engine.recover(recovered, feed.now())
            with store.db:
                engine.emit(
                    "SESSION_RECOVERED",
                    store.session,
                    timestamp=feed.now(),
                    previous_session=resume,
                    continuity_verified=True,
                    notify=True,
                )
        else:
            engine.bootstrap(bars, feed.now())
        store.metadata["resumes"] = resume
        store.report("running")
        print(f"Donchian session_id={store.session}\nSession directory: {store.path}", flush=True)
        heartbeat_at = 0.0
        failures = 0
        while True:
            try:
                tick(engine, feed)
                failures = 0
            except (DataGap, ConnectionError, OSError) as exc:
                # Safe diagnostic, not external exception content or credential-bearing URLs.
                engine.gap(type(exc).__name__, pd.Timestamp.now(tz="UTC"))
                failures = min(failures + 1, 5)
            if time.monotonic() - heartbeat_at >= config.heartbeat_seconds:
                with store.db:
                    engine.emit(
                        "HEARTBEAT",
                        uuid4().hex,
                        timestamp=pd.Timestamp.now(tz="UTC"),
                        last_closed=engine.state["last_closed"],
                        gap=engine.state["gap"],
                        paused=engine.state["paused"],
                        notify=True,
                    )
                    engine.checkpoint()
                heartbeat_at = time.monotonic()
                store.report("running")
            time.sleep(min(60, config.poll_seconds * 2**failures))
    except KeyboardInterrupt:
        status = "stopped"
    except Exception as exc:
        with store.db:
            store.event(
                "ERROR",
                uuid4().hex,
                dict(
                    timestamp=pd.Timestamp.now(tz="UTC"),
                    reason=type(exc).__name__,
                    disclaimer="SIGNAL_ONLY — HYPOTHETICAL — NO EXCHANGE ORDER",
                    notify=True,
                ),
            )
        with (store.path / "errors.log").open("a", encoding="utf-8") as handle:
            handle.write(type(exc).__name__ + "\n")
        raise
    finally:
        with store.db:
            store.event(
                "SESSION_STOPPED",
                store.session,
                dict(
                    timestamp=pd.Timestamp.now(tz="UTC"),
                    status=status,
                    disclaimer="SIGNAL_ONLY — HYPOTHETICAL — NO EXCHANGE ORDER",
                    notify=True,
                ),
            )
        store.report(status)
        store.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["validate", "preflight", "run", "sessions", "status"])
    parser.add_argument("--config", type=Path, default=DEFAULT)
    parser.add_argument("--mode", choices=["signal-only"], default="signal-only")
    parser.add_argument("--preflight", type=Path)
    parser.add_argument(
        "--resume", help="Preserve same account stream in a new linked process session"
    )
    parser.add_argument("--session")
    args = parser.parse_args(argv)
    try:
        config, output, context = load(args.config)
        if args.action == "validate":
            print(
                encode(
                    dict(
                        status="VALID_CONFIG_ONLY",
                        candidates=6,
                        scenarios=2,
                        public_feed_acceptance="PENDING",
                        orders_enabled=False,
                    )
                )
            )
        elif args.action in {"sessions", "status"}:
            if args.action == "status" and not args.session:
                raise ValueError("status requires --session SESSION_ID")
            print(json.dumps(inspect(output / "forward.sqlite", args.session), indent=2))
        elif args.action == "preflight":
            _, _, _, scope = public_preflight(config, context, PublicBroker(OKXDemoBroker()))
            directory = ROOT / "reports/forward/donchian_preflight"
            directory.mkdir(parents=True, exist_ok=True)
            receipt = directory / f"{new_id()}.json"
            receipt.write_text(
                encode(
                    dict(
                        status="PUBLIC_PREFLIGHT_OK",
                        created_at=pd.Timestamp.now(tz="UTC"),
                        config_sha256=sha256(args.config),
                        code_sha256=code_identity()["code_sha256"],
                        resolved=scope,
                        note="Public metadata + confirmed warmup only; no orders/session started",
                    )
                ),
                encoding="utf-8",
            )
            print(f"Public preflight OK. Receipt: {receipt}")
        else:
            if not args.preflight:
                raise ValueError(
                    "run requires --preflight RECEIPT; user must validate public feed first"
                )
            run(args.config, args.preflight, args.resume)
        return 0
    except (ValueError, OSError, KeyError, RuntimeError, sqlite3.Error) as exc:
        reason = (
            str(exc) if type(exc) is ValueError or isinstance(exc, DataGap) else type(exc).__name__
        )
        parser.exit(
            2,
            f"Donchian blocked: {reason[:400]}\n",
        )
