"""Optional isolated observer; notifications stay outside the financial runner."""

import argparse
import json
import sqlite3
import time

from quant_lab.forward.donchian import DISCLAIMER
from quant_lab.forward.donchian_config import OUTPUT, ROOT
from quant_lab.notifications.formatter import safe_text
from quant_lab.notifications.forward_watcher import (
    atomic_state,
    journal,
    load_telegram_env,
    observer_lock,
)
from quant_lab.notifications.telegram import TelegramNotifier, enabled


def format_alert(event, session):
    # Match the RMM watcher's quiet heartbeat policy; keep journal/cursor progress.
    if event.get("notify") is not True or event.get("kind") == "HEARTBEAT":
        return None
    lines = [DISCLAIMER, safe_text(event.get("kind")), f"Session: {safe_text(session)}"]
    fields = (
        "timestamp",
        "instrument",
        "candidate",
        "scenario",
        "side",
        "candidates",
        "price",
        "entry_price",
        "exit_price",
        "stop",
        "target",
        "quantity",
        "entry_fee",
        "exit_fee",
        "slippage",
        "spread",
        "net_pnl",
        "reason",
        "drawdown_pct",
        "gap",
        "paused",
        "coverage",
        "previous_session",
    )
    for key in fields:
        if event.get(key) is not None:
            lines.append(f"{key}: {safe_text(event[key])}")
    for entry in event.get("entries", [])[:12]:
        lines.append(
            " | ".join(
                f"{k}={safe_text(entry.get(k))}"
                for k in (
                    "candidate",
                    "scenario",
                    "price",
                    "stop",
                    "target",
                    "quantity",
                    "risk_budget",
                    "entry_fee",
                )
            )
        )
    return "\n".join(lines)[:3900]


def poll(db_path, state_path, notifier=None, *, dry_run=False, replay=False, output=print):
    state = json.loads(state_path.read_text()) if state_path.exists() and not dry_run else None
    with journal(db_path) as db:
        db.execute("BEGIN")
        high = db.execute("SELECT COALESCE(MAX(rowid),0) FROM events").fetchone()[0]
        if state is None:
            state = dict(
                database=str(db_path.resolve()),
                cursor=0 if replay else high,
                anchor=None,
                pending=None,
            )
        if state["database"] != str(db_path.resolve()) or state["cursor"] > high:
            raise ValueError("Donchian watcher journal replaced; preserve cursor")
        if state["anchor"]:
            row = db.execute("SELECT id FROM events WHERE rowid=?", (state["cursor"],)).fetchone()
            if not row or row[0] != state["anchor"]:
                raise ValueError("Donchian watcher event anchor changed")
        if state["pending"]:
            # Delivery interrupted: do not resend a possibly delivered message.
            pending = state["pending"]
            state.update(
                cursor=pending["rowid"],
                anchor=pending["id"],
                pending=None,
                last_delivery="interrupted_unknown",
            )
        rows = db.execute(
            "SELECT rowid,id,session,data FROM events WHERE rowid>? ORDER BY rowid LIMIT 200",
            (state["cursor"],),
        ).fetchall()
        sessions = {s: json.loads(d) for s, d in db.execute("SELECT id,data FROM sessions")}
    for rowid, key, session, data in rows:
        cfg = sessions[session]["config"]["forward"]
        if (
            cfg.get("study_id") != "eth_donchian_short_prospective_v1"
            or cfg.get("mode") != "signal_only"
            or cfg.get("trading_enabled") is not False
            or cfg.get("send_orders") is not False
            or cfg.get("allow_live_trading") is not False
        ):
            raise ValueError("Unsafe/incompatible Donchian notification session")
        message = format_alert(json.loads(data), session)
        if message:
            if dry_run:
                output(message)
            else:
                state["pending"] = dict(rowid=rowid, id=key)
                atomic_state(state_path, state)
                state["last_delivery"] = notifier.send(message).status
        state.update(cursor=rowid, anchor=key, pending=None)
        if not dry_run:
            atomic_state(state_path, state)
    if not dry_run:
        atomic_state(state_path, state)
    return len(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    directory = ROOT / OUTPUT
    if directory.resolve() != directory:
        parser.exit(2, "Dedicated Donchian directory cannot be aliased\n")
    db = directory / "forward.sqlite"
    state = directory / "donchian_telegram_state.json"
    try:
        if args.dry_run:
            poll(db, state, dry_run=True, replay=True)
            return 0
        load_telegram_env(ROOT / ".env")
        if not enabled():
            print("Telegram disabled; no watcher started")
            return 0
        notifier = TelegramNotifier.from_environment()
        with observer_lock(directory / "donchian_telegram.lock"):
            while True:
                poll(db, state, notifier)
                if args.once:
                    return 0
                time.sleep(2)
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError, KeyError, sqlite3.Error):
        parser.exit(2, "Donchian watcher blocked; preserve journal/cursor and review\n")
