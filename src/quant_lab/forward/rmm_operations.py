"""Read-only RMM preflight and stopped signal-stage verification."""

import argparse
import json
import sqlite3
from pathlib import Path

import pandas as pd

from quant_lab.brokers.okx_demo import OKXDemoBroker
from quant_lab.experiments import provenance
from quant_lab.forward.config import load_config
from quant_lab.forward.feeds import instrument_lookup
from quant_lab.forward.store import encode, identity

ROOT = Path(__file__).resolve().parents[3]
DEFAULT = ROOT / "configs/forward/okx_demo_rmm_4h.yaml"


def verify(session, config, code, *, telegram_verified=False):
    session = Path(session).resolve()
    metadata = json.loads((session / "session.json").read_text(encoding="utf-8"))
    forward = metadata["config"]["forward"]
    expected = config.model_dump(mode="json") | {"instruments": forward["instruments"]}
    if (
        metadata["status"] != "stopped"
        or forward["mode"] != "signal_only"
        or forward["data_protocol"] != "rmm_4h"
        or metadata["provenance"]["code_sha256"] != code["code_sha256"]
        or forward["parameters"] != config.parameters
        or forward["demo_strategy"] != config.demo_strategy
        or forward != expected
        or pd.Timestamp(metadata["end"]) - pd.Timestamp(metadata["start"]) < pd.Timedelta(hours=4)
    ):
        raise ValueError("Require stopped, same-code RMM SIGNAL_ONLY stage >=4h")
    with sqlite3.connect((session.parent / "forward.sqlite").as_uri() + "?mode=ro", uri=True) as db:
        row = db.execute(
            "SELECT data FROM sessions WHERE id=?", (metadata["session_id"],)
        ).fetchone()
        if not row or json.loads(row[0]) != metadata:
            raise ValueError("Session metadata does not match durable journal")
        events = [
            json.loads(r[0])
            for r in db.execute(
                "SELECT data FROM events WHERE session=? ORDER BY rowid", (metadata["session_id"],)
            )
        ]
    if any(
        e["kind"] in {"DATA_GAP", "ERROR", "QUOTE_UNAVAILABLE", "RECOVERY_REVIEW_REQUIRED"}
        for e in events
    ):
        raise ValueError("Signal-stage operational incidents require a fresh verification stage")
    evaluated = {
        e["symbol"] for e in events if e["kind"] == "RMM_CANDLE_EVALUATED" and not e["recovering"]
    }
    if evaluated != set(config.instruments) or not any(e["kind"] == "HEARTBEAT" for e in events):
        raise ValueError(
            "Require confirmed live 4h evaluations for all configured assets and heartbeat"
        )
    if not any(
        e["kind"] == "ORDER_INTENT_CREATED"
        and e.get("strategy") == config.demo_strategy
        and e.get("reason") == "RMM_ENTRY"
        and e.get("target_quantity", 0) > 0
        for e in events
    ):
        raise ValueError("Require a valid selected MAIN shadow entry to verify quotes and sizing")
    if telegram_verified is not True:
        raise ValueError("Confirm actual Telegram startup/alerts before --telegram-verified")
    return dict(
        session=str(session),
        event_sha256=identity(encode(events)),
        code_sha256=code["code_sha256"],
        instruments=forward["instruments"],
        config_sha256=identity(encode(metadata["config"])),
        telegram_verified=True,
    )


def check_receipt(path, config, code, instruments):
    receipt = json.loads(Path(path).read_text(encoding="utf-8"))
    current = verify(
        receipt["session"], config, code, telegram_verified=receipt.get("telegram_verified")
    )
    if receipt != current or current["instruments"] != instruments:
        raise ValueError("Verification receipt/configuration/instruments changed")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only RMM demo preflight")
    parser.add_argument(
        "action",
        choices=["validate", "connect", "instruments", "warmup", "account", "order", "verify"],
    )
    parser.add_argument("--telegram-verified", action="store_true")
    parser.add_argument("--config", type=Path, default=DEFAULT)
    parser.add_argument("--session", type=Path)
    parser.add_argument(
        "--receipt", type=Path, default=ROOT / "reports/forward/rmm_verification.json"
    )
    args = parser.parse_args(argv)
    config, _, _ = load_config(args.config)
    if config.data_protocol != "rmm_4h":
        raise ValueError("RMM configuration required")
    if args.action == "validate":
        print(encode(config.model_dump(mode="json")))
    elif args.action == "connect":
        print(OKXDemoBroker().server_time())
    elif args.action == "instruments":
        from dataclasses import asdict

        instruments, _ = instrument_lookup(config, OKXDemoBroker())
        print(encode({k: asdict(v) for k, v in instruments.items()}))
    elif args.action == "warmup":
        from quant_lab.market_data.okx import DataGap, OKXMarketData

        broker = OKXDemoBroker()
        instruments, _ = instrument_lookup(config, broker)
        feed = OKXMarketData(broker, list(instruments))
        failures = 0
        for instrument in instruments:
            try:
                bars = feed.rmm_history(instrument, config.warmup_bars)
            except DataGap as exc:
                failures += 1
                print(str(exc), flush=True)
            else:
                print(
                    f"{instrument}: {len(bars)} confirmed continuous 4h bars; "
                    f"source={feed.rmm_sources[instrument]}",
                    flush=True,
                )
        if failures:
            parser.exit(1, "RMM warmup not ready; no session, receipt or orders created.\n")
    elif args.action == "account":
        from quant_lab.brokers.okx_execution import OKXDemoExecution

        broker = OKXDemoExecution()
        instruments, _ = instrument_lookup(config, broker)
        instrument = next(
            i
            for i in instruments
            if i.startswith("ETH-" if "eth" in config.demo_strategy else "BTC-")
        )
        broker.account_ready(instrument)
        broker.entry_balance_ready()
        print(
            "Demo authentication, net_mode, isolated 1x, instrument access and positive trading "
            "equity verified (GET only; sufficient margin not guaranteed)"
        )
    elif args.action == "order":
        from quant_lab.brokers.okx_execution import DemoAPIError, OKXDemoExecution

        if not args.session:
            parser.error("order requires --session")
        session = args.session.resolve()
        metadata = json.loads((session / "session.json").read_text(encoding="utf-8"))
        if metadata["config"]["forward"].get("data_protocol") != "rmm_4h":
            parser.error("order requires an RMM session")
        with sqlite3.connect(
            (session.parent / "forward.sqlite").as_uri() + "?mode=ro", uri=True
        ) as db:
            orders = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT data FROM orders WHERE session=? ORDER BY rowid",
                    (metadata["session_id"],),
                )
            ]
        broker = OKXDemoExecution(armed=False)
        for order in orders:
            print(f"Durable order: {order['client_id']} status={order['status']}", flush=True)
            try:
                rows = broker.by_client(order["instrument_id"], order["client_id"])
            except DemoAPIError as exc:
                print(str(exc), flush=True)
                if exc.code == "51603":
                    print(
                        "Order not found by clOrdId; checking current demo occupancy (GET only).",
                        flush=True,
                    )
                    for endpoint, label, fields in (
                        (
                            "/api/v5/account/positions",
                            "Current positions",
                            ("instId", "pos", "posSide", "avgPx", "mgnMode", "lever"),
                        ),
                        (
                            "/api/v5/trade/orders-pending",
                            "Pending orders",
                            ("instId", "ordId", "clOrdId", "side", "sz", "state"),
                        ),
                    ):
                        try:
                            snapshot = broker.get(endpoint, {"instId": order["instrument_id"]})
                            print(
                                label
                                + ": "
                                + encode(
                                    [
                                        {field: row.get(field) for field in fields}
                                        for row in snapshot
                                        if row.get("instId") == order["instrument_id"]
                                    ]
                                ),
                                flush=True,
                            )
                        except RuntimeError as diagnostic:
                            print(f"{label} unavailable: {diagnostic}", flush=True)
                    try:
                        start_ms = (
                            int(pd.Timestamp(order["submitted_at"]).timestamp() * 1000) - 60000
                        )
                        fills = broker.get(
                            "/api/v5/trade/fills",
                            {
                                "instId": order["instrument_id"],
                                "begin": str(start_ms),
                                "limit": "100",
                            },
                        )
                        fields = (
                            "instId",
                            "clOrdId",
                            "ordId",
                            "tradeId",
                            "side",
                            "fillSz",
                            "fillPx",
                            "fillTime",
                        )
                        print(
                            "Recent instrument fills (at most 100, since submission minus 60s): "
                            + encode(
                                [
                                    {field: row.get(field) for field in fields}
                                    for row in fills
                                    if row.get("instId") == order["instrument_id"]
                                ]
                            ),
                            flush=True,
                        )
                    except RuntimeError as diagnostic:
                        print(f"Recent fills unavailable: {diagnostic}", flush=True)
                    try:
                        account = broker.get("/api/v5/account/config")
                        print(
                            "API permissions/account mode: "
                            + encode(
                                [
                                    {
                                        field: row.get(field)
                                        for field in ("perm", "acctLv", "posMode")
                                    }
                                    for row in account
                                ]
                            ),
                            flush=True,
                        )
                    except RuntimeError as diagnostic:
                        print(f"Account settings unavailable: {diagnostic}", flush=True)
                parser.exit(
                    1,
                    "Manual review required; submission remains uncertain. "
                    "No journal changes or resubmission.\n",
                )
            except RuntimeError as exc:
                parser.exit(
                    1, f"Order lookup unavailable: {exc}. No submission or journal changes.\n"
                )
            fields = (
                "instId",
                "clOrdId",
                "ordId",
                "state",
                "side",
                "sz",
                "accFillSz",
                "avgPx",
                "fillTime",
            )
            print(encode([{key: row.get(key) for key in fields} for row in rows]))
            if len(rows) != 1:
                parser.exit(
                    1,
                    "Order not uniquely located; manual review required. "
                    "Never resend automatically.\n",
                )
        if not orders:
            print("No durable orders recorded in this session")
        print("GET only; journal unchanged. This diagnostic does not clear the recovery gate.")
    else:
        if not args.session:
            parser.error("verify requires --session")
        proof = verify(
            args.session, config, provenance(ROOT), telegram_verified=args.telegram_verified
        )
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(encode(proof), encoding="utf-8")
        print(args.receipt)
