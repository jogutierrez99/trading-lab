"""Transactional journal and checkpoints; CSV/Markdown are rebuildable views."""

import csv
import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4


def encode(value):
    return json.dumps(value, default=str, sort_keys=True, allow_nan=False)


def identity(*parts):
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()


TABLES = (
    "recovery_bars",
    "bars",
    "signals",
    "order_intents",
    "orders",
    "fills",
    "positions",
    "broker_snapshots",
    "events",
)


class Store:
    def __init__(self, root, config, code):
        root.mkdir(parents=True, exist_ok=True)
        self.lock = (root / ".runner.lock").open("a+b")
        self.lock.seek(0)
        if os.name == "nt":
            import msvcrt

            if (root / ".runner.lock").stat().st_size == 0:
                self.lock.write(b"0")
                self.lock.flush()
            self.lock.seek(0)
            msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        identity_config = self.recovery_config(config)
        self.recovery_scope = identity(encode(identity_config))
        self.stream = identity(encode(identity_config), code["code_sha256"])
        self.session = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12]
        self.path = root / self.session
        self.path.mkdir(exist_ok=False)
        self.db = sqlite3.connect(root / "forward.sqlite", timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, data TEXT)")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS checkpoints (stream TEXT PRIMARY KEY, data TEXT)"
        )
        for table in TABLES:
            self.db.execute(
                f"CREATE TABLE IF NOT EXISTS {table} "
                "(stream TEXT, id TEXT, session TEXT, data TEXT, PRIMARY KEY(stream,id))"
            )
        self.metadata = {
            "session_id": self.session,
            "stream_id": self.stream,
            "start": datetime.now(UTC).isoformat(),
            "end": None,
            "config": config,
            "provenance": code,
            "status": "starting",
        }
        self.db.execute("INSERT INTO sessions VALUES (?,?)", (self.session, encode(self.metadata)))
        self.db.commit()
        (self.path / "session.json").write_text(encode(self.metadata), encoding="utf-8")
        (self.path / "errors.log").touch()

    @staticmethod
    def recovery_config(config):
        identity_config = config
        if config.get("forward", {}).get("data_protocol") == "eth_v1_required_1h_15m":
            eth = config["forward"]["instruments"]["ETH"]
            identity_config = config | {
                "instruments": {
                    key: value for key, value in config.get("instruments", {}).items() if key == eth
                }
            }
        return identity_config

    def gaps(self, unresolved=False):
        """Compatible data incidents survive code upgrades; trading state does not migrate."""
        streams = {self.stream}
        for (data,) in self.db.execute("SELECT data FROM sessions"):
            session = json.loads(data)
            if identity(encode(self.recovery_config(session["config"]))) == self.recovery_scope:
                streams.add(session["stream_id"])
        result = []
        for stream in sorted(streams):
            for key, session, data in self.db.execute(
                "SELECT id,session,data FROM events WHERE stream=? "
                "AND json_extract(data, '$.kind')='DATA_GAP' ORDER BY rowid",
                (stream,),
            ):
                row = json.loads(data)
                if row["kind"] == "DATA_GAP" and (not unresolved or not row.get("resolved")):
                    result.append(
                        row | {"source_stream": stream, "source_session": session, "event_id": key}
                    )
        return result

    def gap_reconnected(self, gap):
        """Recognize a legacy reconnect after this incident, before the next incident."""
        rows = self.db.execute(
            "SELECT data FROM events WHERE stream=? AND rowid > "
            "(SELECT rowid FROM events WHERE stream=? AND id=?) "
            "AND json_extract(data, '$.kind') IN ('DATA_GAP','RECONNECTED') ORDER BY rowid",
            (gap["source_stream"], gap["source_stream"], gap["event_id"]),
        )
        for (data,) in rows:
            row = json.loads(data)
            if row["kind"] == "DATA_GAP":
                break
            if row.get("incident", gap["event_id"]) == gap["event_id"]:
                return True
        return False

    def update_gap(self, gap, **fields):
        row = self.db.execute(
            "SELECT data FROM events WHERE stream=? AND id=?",
            (gap["source_stream"], gap["event_id"]),
        ).fetchone()
        data = json.loads(row[0]) | fields
        self.db.execute(
            "UPDATE events SET data=? WHERE stream=? AND id=?",
            (encode(data), gap["source_stream"], gap["event_id"]),
        )

    def source_bars(self, stream, table="bars"):
        if table not in {"bars", "recovery_bars", "events"}:
            raise ValueError("Unknown recovery source table")
        return [
            json.loads(r[0])
            for r in self.db.execute(
                f"SELECT data FROM {table} WHERE stream=? ORDER BY rowid", (stream,)
            )
        ]

    def put(self, table, key, row):
        if table not in TABLES:
            raise ValueError("Unknown journal table")
        data = encode(row)
        old = self.db.execute(
            f"SELECT data FROM {table} WHERE stream=? AND id=?", (self.stream, key)
        ).fetchone()
        if old:
            if old[0] != data:
                raise ValueError("Conflicting deterministic journal identity")
            return False
        self.db.execute(
            f"INSERT INTO {table} VALUES (?,?,?,?)", (self.stream, key, self.session, data)
        )
        return True

    def event(self, kind, key, data):
        row = {"kind": kind, "key": key, **data}
        self.put("events", identity(kind, key), row)
        table = {
            "MARKET_BAR_CLOSED": "bars",
            "SIGNAL_GENERATED": "signals",
            "ORDER_INTENT_CREATED": "order_intents",
            "POSITION_SNAPSHOT": "positions",
            "BROKER_SNAPSHOT": "broker_snapshots",
        }.get(kind)
        if table:
            self.put(table, key, data)

    def rows(self, table, session=False):
        if table not in TABLES:
            raise ValueError("Unknown table")
        query = f"SELECT data FROM {table} WHERE stream=?"
        params = [self.stream]
        if session:
            query += " AND session=?"
            params.append(self.session)
        return [json.loads(r[0]) for r in self.db.execute(query + " ORDER BY rowid", params)]

    def checkpoint(self, state):
        self.db.execute(
            "INSERT OR REPLACE INTO checkpoints VALUES (?,?)", (self.stream, encode(state))
        )

    def restore(self):
        row = self.db.execute(
            "SELECT data FROM checkpoints WHERE stream=?", (self.stream,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def report(self, status):
        self.metadata["status"] = status
        if status != "running":
            self.metadata["end"] = datetime.now(UTC).isoformat()
        self.db.execute(
            "UPDATE sessions SET data=? WHERE id=?", (encode(self.metadata), self.session)
        )
        self.db.commit()
        (self.path / "session.json").write_text(encode(self.metadata), encoding="utf-8")
        events = self.rows("events", True)
        gaps = self.gaps()
        tables = {
            "quote_events.csv": [r for r in events if r["kind"] == "QUOTE_UNAVAILABLE"],
            "bars.csv": self.rows("bars", True),
            "signals.csv": self.rows("signals", True),
            "order_intents.csv": self.rows("order_intents", True),
            "timing_events.csv": [r for r in events if r["kind"].startswith("TIMING_")],
            "positions_snapshot.csv": self.rows("positions", True),
            "broker_state.csv": self.rows("broker_snapshots", True),
            "monitoring_bars.csv": [r for r in events if r["kind"] == "MONITOR_BAR_CLOSED"],
            "monitoring_warnings.csv": [r for r in events if r["kind"] == "MONITORING_WARNING"],
            "data_gaps.csv": gaps,
            "continuity_audits.csv": [
                a | {"incident": g["event_id"], "blocks_signals": True}
                for g in gaps
                for a in g.get("audits", [])
            ]
            + [r for r in events if r["kind"] == "MONITORING_CONTINUITY_AUDIT"],
            "recovery_events.csv": [r for r in events if r["kind"].startswith("DATA_GAP_")],
        }
        for name, rows in tables.items():
            fields = sorted({k for row in rows for k in row}) or ["no_records"]
            with (self.path / name).open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
        counts = {
            kind: sum(e["kind"] == kind for e in events)
            for kind in sorted({e["kind"] for e in events})
        }
        counts.update(
            {
                "data_gaps_total": len(gaps),
                "data_gaps_resolved": sum(bool(g.get("resolved")) for g in gaps),
                "data_gaps_unresolved": sum(not g.get("resolved", False) for g in gaps),
                "recovered_bars": sum(g.get("recovered_bars", 0) for g in gaps),
                "reconnections": sum(bool(g.get("reconnected")) for g in gaps),
            }
        )
        intents = tables["order_intents.csv"]
        notionals = [r["target_notional"] for r in intents]
        strategies = {}
        for name in self.metadata["config"]["forward"]["strategies"]:
            subset = [r for r in intents if r["strategy"] == name]
            strategies[name] = {
                "signals_generated": len(tables["signals.csv"]),
                "hypothetical_orders": len(subset),
                "average_theoretical_entry": sum(r["estimated_entry_price"] for r in subset)
                / len(subset)
                if subset
                else None,
                "stops": [r["stop_price"] for r in subset],
                "sizes": [r["contracts"] for r in subset],
            }
        # Readiness stays conservative without an independently verified deployment receipt.
        readiness = (
            "BLOCK_DEMO_EXECUTION"
            if status == "failed" or counts["data_gaps_unresolved"] or counts.get("ERROR")
            else "NEEDS_REVIEW"
        )
        if (
            readiness == "NEEDS_REVIEW"
            and not counts.get("QUOTE_UNAVAILABLE")
            and self.metadata.get("parity_receipt")
            and intents
            and self.metadata["config"].get("instruments")
        ):
            readiness = "SIGNAL_PIPELINE_OK"
        sections = [
            "# Forward Test — AI Summary",
            "## Session",
            encode({k: v for k, v in self.metadata.items() if k != "provenance"}),
            "## Data health",
            encode(counts),
            "## Signals",
            encode(strategies),
            "## Timing",
            encode({k: v for k, v in counts.items() if k.startswith("TIMING_")}),
            "## Risk",
            encode(
                {
                    "average_notional": sum(notionals) / len(notionals) if notionals else None,
                    "max_notional": max(notionals, default=None),
                    "max_theoretical_entry_exposure_pct": max(
                        (row.get("exposure_pct", 0) for row in tables["positions_snapshot.csv"]),
                        default=None,
                    ),
                    "entry_exposure_cap_pct": 25,
                    "accounts": "independent alternatives, not a combined portfolio",
                }
            ),
            "## Differences / warnings",
            "OKX EU settlement currency is recorded from API instrument metadata "
            "(USD or USDC, never assumed equivalent). "
            "Binance USD-M USDT evidence is not equivalent. "
            "Quotes and shadow occupancy are estimates, not exchange fills. "
            "No funding, mark-price liquidation "
            "or account PnL replication is claimed. Recovery does not invent missed entries. "
            "Runtime parity/sizing evidence must be reviewed before SIGNAL_PIPELINE_OK. "
            "Demo routing is unavailable.",
            "## Errors",
            encode([e for e in events if e["kind"] == "ERROR"] + gaps),
            "## Readiness",
            readiness,
        ]
        state = self.restore() or {}
        if "shadow_positions" in state:
            from quant_lab.forward.shadow_reporting import render

            shadow = state["shadow_positions"]
            if counts["data_gaps_unresolved"]:
                shadow = {
                    key: row | {"coverage": "DATA_GAP"}
                    if row["status"] == "OPEN" and row["coverage"] == "CONTINUOUS"
                    else row
                    for key, row in shadow.items()
                }
            sections.insert(-2, render(self.path, shadow))
        report = "\n\n".join(sections) + "\n"
        for name in ("summary.md", "ai_summary.md"):
            (self.path / name).write_text(report, encoding="utf-8")

    def close(self):
        self.db.close()
        self.lock.close()
