"""Incremental read-only journal observer with a separate durable delivery cursor."""

import argparse
import json
import logging
import math
import os
import re
import shlex
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from quant_lab.notifications.formatter import format_event
from quant_lab.notifications.telegram import Delivery, TelegramNotifier, enabled

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "results/forward/forward.sqlite"
LOG = logging.getLogger(__name__)
TELEGRAM_VARIABLES = frozenset(
    {
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_NOTIFICATIONS_ENABLED",
        "TELEGRAM_POLL_SECONDS",
    }
)


def load_telegram_env(path: Path) -> None:
    """Load only four Telegram settings; explicit shell variables take precedence.

    Supports single-line KEY=value, optional export, quotes and trailing comments.
    No shell execution, interpolation or changes to OKX/trading variables.
    """
    try:
        content = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return
    except (OSError, UnicodeError):
        raise ValueError("Cannot read project .env; check permissions and UTF-8 encoding") from None
    values = {}
    for line in content.splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", line)
        if not match or match[1] not in TELEGRAM_VARIABLES or match[1] in os.environ:
            continue
        try:
            parts = shlex.split(match[2], comments=True, posix=True)
            if len(parts) > 1:
                raise ValueError
        except ValueError:
            raise ValueError(
                "Invalid Telegram assignment in .env; use single-line values"
            ) from None
        values[match[1]] = parts[0] if parts else ""
    for name, value in values.items():
        os.environ.setdefault(name, value)


@contextmanager
def observer_lock(path: Path):
    """Own OS lock only; never opens .runner.lock. Released even on process death."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            if path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def atomic_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=path.name + ".", delete=False
        ) as handle:
            temp = Path(handle.name)
            json.dump(state, handle, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


@contextmanager
def journal(path: Path):
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.25)
    try:
        connection.execute("PRAGMA query_only=ON")
        yield connection
    finally:
        connection.close()


def anchor(connection, rowid: int) -> list[str] | None:
    row = connection.execute("SELECT stream,id FROM events WHERE rowid=?", (rowid,)).fetchone()
    return list(row) if row else None


def signal_only(connection, session: str) -> bool:
    row = connection.execute("SELECT data FROM sessions WHERE id=?", (session,)).fetchone()
    try:
        config = json.loads(row[0])["config"]["forward"] if row else {}
        return (
            config.get("mode") == "signal_only"
            and config.get("environment") == "demo"
            and config.get("broker") == "okx"
            and config.get("trading_enabled") is False
            and config.get("allow_live_trading") is False
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


class ForwardWatcher:
    """Caller holds observer_lock for the lifetime of a non-dry observer."""

    def __init__(
        self,
        db: Path,
        notifier=None,
        *,
        dry_run=False,
        replay_last=None,
        include_rejected=False,
        output=print,
    ):
        self.db = db.resolve()
        self.state_path = self.db.with_name(self.db.stem + "_telegram_watcher_state.json")
        self.lock_path = self.db.with_name(self.db.stem + "_telegram_watcher.lock")
        self.notifier, self.dry_run = notifier, dry_run
        self.replay_last, self.include_rejected, self.output = replay_last, include_rejected, output
        self.state = None
        self.highwater = 0
        if not dry_run and self.state_path.exists():
            if replay_last is not None:
                raise ValueError("Replay requires dry-run or a journal without watcher state")
            try:
                state = json.loads(self.state_path.read_text(encoding="utf-8"))
                valid = (
                    state["version"] == 1
                    and state["database"] == str(self.db)
                    and type(state["cursor"]) is int
                    and state["cursor"] >= 0
                    and isinstance(state["failures"], list)
                    and len(state["failures"]) <= 100
                    and (state["cursor"] == 0 or self._valid_anchor(state["anchor"]))
                    and (
                        state["pending"] is None
                        or (
                            type(state["pending"]["rowid"]) is int
                            and state["pending"]["rowid"] > state["cursor"]
                            and self._valid_anchor(state["pending"]["anchor"])
                        )
                    )
                )
            except (ValueError, TypeError, KeyError):
                valid = False
            if not valid:
                raise ValueError("Invalid watcher state; preserve it and review before restarting")
            self.state = state

    @staticmethod
    def _valid_anchor(value):
        return (
            isinstance(value, list) and len(value) == 2 and all(isinstance(v, str) for v in value)
        )

    @property
    def cursor(self) -> int:
        return self.state["cursor"] if self.state else 0

    def save(self, state: dict) -> None:
        if not self.dry_run:
            atomic_state(self.state_path, state)
        self.state = state

    def finish(self, rowid: int, identity: list, status: str, attempts: int = 0) -> None:
        failures = self.state["failures"]
        if status not in {"sent", "ignored", "dry_run"}:
            failures = (failures + [{"rowid": rowid, "status": status, "attempts": attempts}])[
                -100:
            ]
            LOG.warning("Notification row %d: %s", rowid, status)
        self.save(
            self.state
            | {"cursor": rowid, "anchor": identity, "pending": None, "failures": failures}
        )

    def poll(self, *, through: int | None = None) -> int | None:
        """Read at most 200 rows. None means retryable SQLite failure; no cursor change."""
        try:
            with journal(self.db) as connection:
                connection.execute("BEGIN")
                self.highwater = connection.execute(
                    "SELECT COALESCE(MAX(rowid),0) FROM events"
                ).fetchone()[0]
                if self.state is None:
                    cursor = self.highwater
                    if self.replay_last:
                        rows = connection.execute(
                            "SELECT rowid FROM events ORDER BY rowid DESC LIMIT ?",
                            (self.replay_last,),
                        ).fetchall()
                        cursor = rows[-1][0] - 1 if rows else 0
                    # rowids can have holes. Anchor the last existing predecessor.
                    cursor = connection.execute(
                        "SELECT COALESCE(MAX(rowid),0) FROM events WHERE rowid<=?", (cursor,)
                    ).fetchone()[0]
                    self.save(
                        {
                            "version": 1,
                            "database": str(self.db),
                            "cursor": cursor,
                            "anchor": anchor(connection, cursor),
                            "pending": None,
                            "failures": [],
                        }
                    )
                if self.cursor and anchor(connection, self.cursor) != self.state["anchor"]:
                    raise ValueError(
                        "Journal replaced/truncated; preserve state and review manually"
                    )
                pending = self.state["pending"]
                if pending:
                    if anchor(connection, pending["rowid"]) != pending["anchor"]:
                        raise ValueError("Pending event identity changed; review journal and state")
                    # An interrupted HTTP request cannot be safely replayed automatically.
                    self.finish(pending["rowid"], pending["anchor"], "interrupted_unknown")
                limit = self.highwater if through is None else min(through, self.highwater)
                rows = connection.execute(
                    "SELECT rowid,stream,id,session,data FROM events "
                    "WHERE rowid>? AND rowid<=? ORDER BY rowid ASC LIMIT 200",
                    (self.cursor, limit),
                ).fetchall()
                modes = {
                    session: signal_only(connection, session) for session in {r[3] for r in rows}
                }
            # End the read transaction BEFORE network I/O/backoff, so WAL can checkpoint.
        except sqlite3.Error:
            LOG.warning("Journal unavailable or temporarily locked; retrying on next poll")
            return None
        for rowid, stream, event_id, session, raw in rows:
            identity = [stream, event_id]
            try:
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError("Event must be an object")
                message = format_event(data, session, include_rejected=self.include_rejected)
            except (ValueError, TypeError):
                self.finish(rowid, identity, "invalid_event")
                continue
            if message is None:
                self.finish(rowid, identity, "ignored")
            elif not modes[session]:
                self.finish(rowid, identity, "unsupported_session")
            elif self.dry_run:
                self.output(message)
                self.finish(rowid, identity, "dry_run")
            else:
                # Pending is not a completed cursor: restart records the uncertainty explicitly.
                self.save(self.state | {"pending": {"rowid": rowid, "anchor": identity}})
                try:
                    delivery = self.notifier.send(message)
                except Exception:
                    # Boundary guard for unexpected transport failures; never log exception text.
                    delivery = Delivery("client_unknown", 0)
                self.finish(rowid, identity, delivery.status, delivery.attempts)
        return len(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only SIGNAL_ONLY Telegram journal observer")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--poll-seconds", type=float)
    parser.add_argument(
        "--replay-last", type=int, help="Last N journal rows, explicitly (max 10000)"
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print only; no state writes or HTTP"
    )
    parser.add_argument("--include-rejected", action="store_true")
    parser.add_argument(
        "--startup-message", action="store_true", help="One startup alert, optional"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        load_telegram_env(ROOT / ".env")
        try:
            poll = (
                args.poll_seconds
                if args.poll_seconds is not None
                else float(os.getenv("TELEGRAM_POLL_SECONDS", "2"))
            )
        except ValueError:
            raise ValueError("TELEGRAM_POLL_SECONDS must be a number") from None
        if not math.isfinite(poll) or not 0.1 <= poll <= 3600:
            raise ValueError("Poll seconds must be finite, between 0.1 and 3600")
        if args.replay_last is not None and not 0 <= args.replay_last <= 10000:
            raise ValueError("Replay must be between 0 and 10000 rows")
        if not args.dry_run and not enabled():
            print("Telegram notifications disabled; set TELEGRAM_NOTIFICATIONS_ENABLED=true")
            return 0
        notifier = None if args.dry_run else TelegramNotifier.from_environment()
        db = args.db if args.db.is_absolute() else ROOT / args.db
        # Acquire before loading state: two processes must never read the same old cursor.
        lock = db.resolve().with_name(db.stem + "_telegram_watcher.lock")
        if args.dry_run:
            return watch(args, db, notifier, poll)
        with observer_lock(lock):
            return watch(args, db, notifier, poll)
    except KeyboardInterrupt:
        print("Watcher stopped; completed cursor and any pending delivery are durable")
        return 0
    except ValueError as exc:
        # All configuration errors originate here and contain no supplied values/secrets.
        LOG.error("%s", str(exc) if not isinstance(exc, json.JSONDecodeError) else "Invalid JSON")
        return 2
    except OSError as exc:
        # Log numeric diagnostics and our last frame, never exception text/paths:
        # an OSError may also originate during client setup, before locking.
        location = "main"
        frame = exc.__traceback__
        while frame is not None:
            if frame.tb_frame.f_code.co_filename == __file__:
                location = f"{frame.tb_frame.f_code.co_name}:{frame.tb_lineno}"
            frame = frame.tb_next
        LOG.error(
            "Watcher OS error at %s (errno=%s, winerror=%s); "
            "check the failing operation before changing state or locks",
            location,
            exc.errno,
            getattr(exc, "winerror", None),
        )
        return 2


def watch(args, db: Path, notifier, poll: float) -> int:
    watcher = ForwardWatcher(
        db,
        notifier,
        dry_run=args.dry_run,
        replay_last=args.replay_last,
        include_rejected=args.include_rejected,
    )
    startup_done, through = False, None
    while True:
        count = watcher.poll(through=through)
        if count is not None and not startup_done:
            startup_done = True
            if args.startup_message:
                message = (
                    "🟢 Trading Lab Telegram watcher started\nDatabase: forward.sqlite\n"
                    "Mode: READ ONLY\nTrading mode: SIGNAL_ONLY observer\n"
                    "Historical alerts: "
                    + (
                        "explicit replay"
                        if args.replay_last
                        else "saved cursor or skipped on first start"
                    )
                )
                if args.dry_run:
                    print(message)
                else:
                    try:
                        result = notifier.send(message)
                        if result.status != "sent":
                            LOG.warning("Startup notification failed; observer continues")
                    except Exception:
                        LOG.warning("Startup notification failed; observer continues")
        if args.once:
            if count is None:
                return 1
            if through is None:
                through = watcher.highwater
            if watcher.cursor >= through or count == 0:
                return 0
        if count is None or count < 200:
            time.sleep(poll)


if __name__ == "__main__":
    raise SystemExit(main())
