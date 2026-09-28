"""Bounded startup/recovery and user-operated forward loop."""

import argparse
import importlib.util
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import pandas as pd

from quant_lab.brokers.okx_demo import OKXDemoBroker
from quant_lab.experiments import provenance
from quant_lab.forward.config import load_config
from quant_lab.forward.engine import ForwardEngine
from quant_lab.forward.feeds import history, instrument_lookup
from quant_lab.forward.recovery import detect, recover_incidents
from quant_lab.forward.store import Store
from quant_lab.market_data.okx import BARS, DataGap, FeedIssue, OKXMarketData
from quant_lab.mtf_features import STEPS

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "configs/forward/okx_demo.yaml"


def recover(engine, feed, *, initial=False):
    if engine.store.gaps(unresolved=True):
        if not recover_incidents(engine, feed):
            raise DataGap("RECOVERY_INCOMPLETE: required candle continuity is not verified")
        return
    collected = []
    for instrument in engine.config.instruments.values():
        for timeframe in BARS:
            frame = engine.book.frame(instrument, timeframe)
            since = frame.index[-1] if len(frame) else None
            if not engine.config.required_feed(instrument, timeframe):
                latest = engine.monitor_latest.get(f"{instrument}|{timeframe}")
                since = pd.Timestamp(latest["timestamp"]) if latest else None
            bars, warning = history(engine.config, feed, instrument, timeframe, since=since)
            if warning:
                with engine.store.db:
                    engine.monitoring_warning(instrument, timeframe, warning["reason"])
            collected.extend(bars)
    if initial and not engine.store.restore():
        engine.bootstrap(collected)
        return
    known_quarters = engine.book.bars.get((engine.eth, "15m"), {})
    missed = any(
        b.instrument_id == engine.eth and b.timeframe == "15m" and b.timestamp not in known_quarters
        for b in collected
    )
    if missed:
        engine.invalidate_timing("disconnect_or_restart_no_retroactive_entry")
    # Recovery restores context/occupancy, never submits delayed hypothetical entries.
    for bar in sorted(collected, key=lambda b: (b.close_time, b.timeframe != "15m")):
        engine.ingest(bar, feed.quote, recovering=True)


def heartbeat(engine, feed, status):
    last = {
        f"{inst}:{tf}": str(max(rows) + STEPS[tf])
        for (inst, tf), rows in engine.book.bars.items()
        if rows
    }
    key = uuid4().hex
    with engine.store.db:
        now = feed.now()
        for row in engine.monitor_latest.values():
            tf = row["timeframe"]
            closed = pd.Timestamp(row["timestamp"]) + STEPS[tf]
            if now - closed > STEPS[tf] + pd.Timedelta(seconds=90):
                engine.monitoring_warning(
                    row["instrument_id"],
                    tf,
                    f"Stale monitoring feed; last close={closed.isoformat()}",
                )
        engine.store.event(
            "HEARTBEAT",
            key,
            {
                "timestamp": pd.Timestamp.now(tz="UTC"),
                "broker_connection": "public_rest_ok",
                "market_data_connection": status,
                "last_candles": last,
                "monitoring_latest": engine.monitor_latest,
                "runner_status": "running",
                "last_signal": engine.store.rows("signals")[-1:],
            },
        )


def run(config_path, *, max_updates=None):
    config, inherited, output = load_config(config_path)
    if importlib.util.find_spec("websockets") is None:
        raise ValueError('Install forward dependencies: python -m pip install -e ".[dev,forward]"')
    broker = OKXDemoBroker()
    instruments, warnings = instrument_lookup(config, broker)
    feed = OKXMarketData(broker, list(instruments))
    feed.required_feeds = {
        (i, tf) for i in instruments for tf in BARS if config.required_feed(i, tf)
    }
    resolved = {
        "forward": config.model_dump(mode="json"),
        "inherited": inherited.model_dump(mode="json"),
        "instruments": {key: asdict(value) for key, value in instruments.items()},
    }
    store = Store(output, resolved, provenance(ROOT))
    for receipt in sorted((ROOT / "reports/forward/preflight").glob("*.json"), reverse=True):
        try:
            proof = json.loads(receipt.read_text(encoding="utf-8"))
            if (
                proof.get("code_sha256") == store.metadata["provenance"]["code_sha256"]
                and proof.get("signal_parity_tests") == "passed"
                and proof.get("dependencies") == store.metadata["provenance"].get("dependencies")
            ):
                store.metadata["parity_receipt"] = str(receipt.relative_to(ROOT))
                break
        except (ValueError, OSError):
            continue
    status = "stopped"
    try:
        engine = ForwardEngine(config, inherited, instruments, store)
        with store.db:
            for warning in warnings:
                engine.monitoring_warning(**warning)
        private = all(os.getenv(n) for n in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"))
        snapshot = (
            broker.reconcile() if private else {"status": "PUBLIC_ONLY", "private_state": "unknown"}
        )
        with store.db:
            store.event("BROKER_SNAPSHOT", store.session, snapshot)
        try:
            recover(engine, feed, initial=True)
        except DataGap as exc:
            detect(engine, str(exc))
            raise
        print(f"SIGNAL_ONLY session: {store.path}", flush=True)
        store.report("running")
        retries, updates, last_heartbeat = 0, 0, 0.0
        while max_updates is None or updates < max_updates:
            bar = None
            try:
                for bar in feed.updates():
                    if isinstance(bar, FeedIssue):
                        with store.db:
                            engine.monitoring_warning(bar.instrument_id, bar.timeframe, bar.reason)
                        continue
                    if bar is not None:
                        known = engine.book.bars.get((bar.instrument_id, bar.timeframe), {})
                        if bar.timestamp in known:
                            engine.book.add(bar)  # validates retransmissions as well
                            continue
                        # Detect prolonged delay even if a socket remains technically connected.
                        now = feed.now()
                        if now - bar.close_time > pd.Timedelta(seconds=90):
                            if config.required_feed(bar.instrument_id, bar.timeframe):
                                raise DataGap("Late candle requires REST recovery")
                            with store.db:
                                engine.monitoring_warning(
                                    bar.instrument_id, bar.timeframe, "Late monitoring candle"
                                )
                        engine.ingest(bar, feed.quote)
                        updates += 1
                    if time.monotonic() - last_heartbeat >= config.heartbeat_seconds:
                        now = feed.now()
                        for (inst, tf), rows in engine.book.bars.items():
                            if rows and now - (max(rows) + STEPS[tf]) > STEPS[tf] + pd.Timedelta(
                                seconds=90
                            ):
                                raise DataGap(f"Stale candle stream: {inst} {tf}")
                        heartbeat(engine, feed, "connected")
                        store.report("running")
                        last_heartbeat = time.monotonic()
                    if max_updates is not None and updates >= max_updates:
                        break
                else:
                    raise ConnectionError("WebSocket stream ended")
            except (ConnectionError, OSError, TimeoutError, DataGap) as exc:
                retries += 1
                # A failed transaction may have touched in-memory candle/policy state.
                # Restore only committed state before attempting recovery.
                engine = ForwardEngine(config, inherited, instruments, store)
                detect(
                    engine,
                    type(exc).__name__,
                    first_new=bar if not isinstance(bar, FeedIssue) else None,
                )
                engine.invalidate_timing("data_gap")
                while True:
                    if retries > config.max_reconnects:
                        raise RuntimeError("Reconnect limit reached") from None
                    time.sleep(min(2**retries, 30))
                    try:
                        recover(engine, feed)
                        break
                    except (ConnectionError, OSError, TimeoutError, DataGap):
                        retries += 1
                        store.report("running")
                        engine = ForwardEngine(config, inherited, instruments, store)
    except KeyboardInterrupt:
        status = "stopped"
    except Exception as exc:
        status = "failed"
        detail = (
            str(exc)
            if isinstance(exc, DataGap)
            else "Forward stopped; check connectivity/configuration and journal"
        )
        with store.db:
            if isinstance(exc, DataGap) and not store.gaps(unresolved=True):
                store.event("DATA_GAP", uuid4().hex, {"reason": detail, "resolved": False})
            store.event(
                "ERROR",
                uuid4().hex,
                {
                    "exception_type": type(exc).__name__,
                    "message": detail,
                },
            )
        (store.path / "errors.log").write_text(
            type(exc).__name__ + ": " + detail + "\n", encoding="utf-8"
        )
        raise
    finally:
        store.report(status)
        store.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="OKX EU SIGNAL_ONLY; no order routing")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--mode", choices=["signal-only"], default="signal-only")
    parser.add_argument(
        "--max-updates", type=int, help="Stop after a bounded number of confirmed WS updates"
    )
    args = parser.parse_args(argv)
    if args.max_updates is not None and args.max_updates < 1:
        parser.error("--max-updates must be positive")
    run(args.config, max_updates=args.max_updates)


if __name__ == "__main__":
    main()
