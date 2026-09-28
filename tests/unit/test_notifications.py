"""Telegram and observer tests use isolated journals and fake HTTP only."""

import hashlib
import io
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest

from quant_lab.notifications import forward_watcher as fw
from quant_lab.notifications.formatter import format_event
from quant_lab.notifications.telegram import Delivery, NoRedirect, TelegramNotifier

CONFIG = {
    "mode": "signal_only",
    "environment": "demo",
    "broker": "okx",
    "trading_enabled": False,
    "allow_live_trading": False,
}
SIGNAL = {
    "kind": "SIGNAL_GENERATED",
    "strategy": "mtf_trend_pullback_v1",
    "instrument": "ETH-USD_UM_XPERP-310328",
    "side": "long",
    "timestamp": "2026-09-28T12:00:00+00:00",
    "signal_id": "abcdef" * 10,
}


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(fw.os, "environ", fw.os.environ.copy())
    monkeypatch.setattr(fw, "ROOT", tmp_path)
    for name in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_NOTIFICATIONS_ENABLED",
        "TELEGRAM_POLL_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_dotenv_loading_quotes_comments_and_scope(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(
        '\ufeffexport TELEGRAM_BOT_TOKEN="12345:dummy_token" # comment\n'
        "TELEGRAM_CHAT_ID='-123456'\nTELEGRAM_NOTIFICATIONS_ENABLED=true\n"
        "TELEGRAM_POLL_SECONDS=2\nTRADING_ENABLED=true\nOKX_API_SECRET=ignored\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TRADING_ENABLED", "false")
    monkeypatch.delenv("OKX_API_SECRET", raising=False)
    fw.load_telegram_env(path)
    assert fw.os.environ["TELEGRAM_BOT_TOKEN"] == "12345:dummy_token"
    assert fw.os.environ["TELEGRAM_CHAT_ID"] == "-123456"
    assert fw.os.environ["TELEGRAM_NOTIFICATIONS_ENABLED"] == "true"
    assert fw.os.environ["TRADING_ENABLED"] == "false"
    assert "OKX_API_SECRET" not in fw.os.environ


def test_dotenv_shell_precedence_and_no_interpolation(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(
        "TELEGRAM_NOTIFICATIONS_ENABLED=true\nTELEGRAM_CHAT_ID='${PRIVATE}'\n", encoding="utf-8"
    )
    monkeypatch.setenv("TELEGRAM_NOTIFICATIONS_ENABLED", "false")
    fw.load_telegram_env(path)
    assert fw.os.environ["TELEGRAM_NOTIFICATIONS_ENABLED"] == "false"
    assert fw.os.environ["TELEGRAM_CHAT_ID"] == "${PRIVATE}"


def test_dotenv_missing_and_malformed_do_not_disclose_values(tmp_path):
    path = tmp_path / ".env"
    fw.load_telegram_env(path)
    path.write_text(
        'TELEGRAM_POLL_SECONDS=2\nTELEGRAM_BOT_TOKEN="private-invalid\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="Invalid Telegram assignment") as error:
        fw.load_telegram_env(path)
    assert "private-invalid" not in str(error.value)
    assert "TELEGRAM_POLL_SECONDS" not in fw.os.environ


def test_cli_reads_project_dotenv_from_other_cwd(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "TELEGRAM_NOTIFICATIONS_ENABLED=true\nTELEGRAM_POLL_SECONDS=7\n"
        "TELEGRAM_BOT_TOKEN=12345:dummy_token\nTELEGRAM_CHAT_ID=-123456\n",
        encoding="utf-8",
    )
    other = tmp_path / "other"
    other.mkdir()
    (other / ".env").write_text("TELEGRAM_POLL_SECONDS=invalid\n", encoding="utf-8")
    monkeypatch.chdir(other)
    observe = Mock(return_value=0)
    monkeypatch.setattr(fw, "watch", observe)
    assert fw.main(["--db", str(tmp_path / "fake.sqlite"), "--once"]) == 0
    assert observe.call_args.args[-1] == 7
    assert isinstance(observe.call_args.args[2], TelegramNotifier)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "forward.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE events (stream TEXT,id TEXT,session TEXT,data TEXT,"
            "PRIMARY KEY(stream,id))"
        )
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY,data TEXT)")
        conn.execute(
            "INSERT INTO sessions VALUES (?,?)",
            ("session", json.dumps({"config": {"forward": CONFIG}})),
        )
    return path


def add(db, data=None, *, stream="stream", session="session"):
    with sqlite3.connect(db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] + 1
        conn.execute(
            "INSERT INTO events VALUES (?,?,?,?)",
            (stream, str(n), session, json.dumps(SIGNAL if data is None else data)),
        )
    return n


def notifier():
    return Mock(send=Mock(return_value=Delivery("sent", 1)))


def test_signal_format_real_payload():
    message = format_event(SIGNAL, "session")
    for expected in (
        "SIGNAL GENERATED",
        SIGNAL["strategy"],
        SIGNAL["instrument"],
        "Side: long",
        "2026-09-28T12:00:00Z",
        "OKX DEMO / SIGNAL_ONLY",
        "Signal ID: abcdef",
        "Execution: SIGNAL ONLY — no exchange order sent",
    ):
        assert expected in message
    assert SIGNAL["signal_id"] not in message


def test_intent_is_hypothetical():
    from dataclasses import asdict

    from quant_lab.brokers.base import OrderIntent

    intent = OrderIntent(
        "id",
        SIGNAL["timestamp"],
        "strategy",
        "ETH",
        SIGNAL["instrument"],
        "buy",
        "market_hypothetical",
        100,
        0.03,
        "30",
        3000,
        3001,
        2900,
        50,
        "signal",
        "BASELINE",
    )
    message = format_event({"kind": "ORDER_INTENT_CREATED", **asdict(intent)}, "session")
    for expected in (
        "HYPOTHETICAL ORDER INTENT",
        "Reference price: 3000",
        "Estimated entry: 3001",
        "Target notional: 100",
        "Quantity: 0.03",
        "Contracts: 30",
        "Stop: 2900",
        "Policy: BASELINE",
        "SIGNAL ONLY — NOT sent to OKX",
        SIGNAL["instrument"],
    ):
        assert expected in message
    assert all(word not in message for word in ("Order sent", "Filled", "Executed"))


@pytest.mark.parametrize(
    "kind",
    ["TIMING_WINDOW_STARTED", "TIMING_FILL_SELECTED", "TIMING_FALLBACK", "TIMING_NOT_EXECUTED"],
)
def test_timing_is_theoretical(kind):
    message = format_event(
        {
            "kind": kind,
            "baseline_entry": 10,
            "deadline": SIGNAL["timestamp"],
            "experimental_entry_price": 9,
            "reason": "reason",
        },
        "s",
    )
    assert "theoretical selection" in message
    assert "Reason: reason" in message
    assert "Baseline entry: 10" in message


@pytest.mark.parametrize(
    "kind",
    [
        "DATA_GAP",
        "DATA_GAP_RESOLVED",
        "DATA_GAP_RECOVERY_FAILED",
        "RECONNECTED",
        "MONITORING_WARNING",
    ],
)
def test_data_health_format(kind):
    message = format_event(
        {
            "kind": kind,
            "instrument": "ETH",
            "timeframe": "15m",
            "reason": "missing candle",
            "resolved": False,
        },
        "s",
    )
    assert "Instrument: ETH" in message and "Timeframe: 15m" in message
    assert "Reason: missing candle" in message and "Resolved: False" in message


def test_error_redaction_and_allowlist(monkeypatch):
    monkeypatch.setenv("OKX_API_SECRET", "dummy-private-value")
    message = format_event(
        {
            "kind": "ERROR",
            "exception_type": "ConnectionError",
            "message": "dummy-private-value https://host/private token=example",
            "credentials": {"secret": "never show nested data"},
        },
        "session",
    )
    assert "FORWARD ERROR" in message and "Exception type: ConnectionError" in message
    assert "Session: session" in message
    assert all(s not in message for s in ("dummy-private-value", "https://", "example", "nested"))


def test_ignore_noise_and_opt_in_rejections():
    for kind in ("HEARTBEAT", "ORDER_SKIPPED_SIGNAL_ONLY", "UNKNOWN", "SIGNAL_REJECTED"):
        assert format_event({"kind": kind}, "s") is None
    assert format_event({"kind": "SIGNAL_REJECTED"}, "s", include_rejected=True)


def test_from_now_incremental_and_restart(db):
    add(db)
    sender = notifier()
    watcher = fw.ForwardWatcher(db, sender)
    assert watcher.poll() == 0 and watcher.cursor == 1
    sender.send.assert_not_called()
    add(db)
    add(db, {"kind": "HEARTBEAT"})
    assert watcher.poll() == 2 and watcher.cursor == 3
    assert sender.send.call_count == 1
    restarted = fw.ForwardWatcher(db, sender)
    assert restarted.poll() == 0
    add(db, stream="new-stream")
    assert restarted.poll() == 1
    assert sender.send.call_count == 2


def test_explicit_replay_is_last_rows_and_cannot_rewind_live_state(db):
    for _ in range(6):
        add(db)
    sender = notifier()
    watcher = fw.ForwardWatcher(db, sender, replay_last=2)
    assert watcher.poll() == 2 and watcher.cursor == 6
    assert sender.send.call_count == 2
    with pytest.raises(ValueError, match="Replay requires"):
        fw.ForwardWatcher(db, sender, replay_last=2)


def test_wal_readonly_bytes_and_writer_during_delivery(db):
    writer = sqlite3.connect(db)
    add(db)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    with fw.journal(db) as conn:
        assert conn.execute("PRAGMA query_only").fetchone() == (1,)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM events")
    sender = notifier()

    def send(message):
        # No observer read transaction remains while HTTP would run.
        assert writer.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
        return Delivery("sent", 1)

    writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    sender.send.side_effect = send
    watcher = fw.ForwardWatcher(db, sender, replay_last=1)
    assert watcher.poll() == 1
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    writer.execute("INSERT INTO events VALUES ('s','new','session',?)", (json.dumps(SIGNAL),))
    assert watcher.poll() == 0  # uncommitted writer is invisible
    writer.commit()
    assert watcher.poll() == 1
    writer.close()
    assert not (db.parent / ".runner.lock").exists()


def test_missing_journal_retry_then_from_now(tmp_path):
    missing = tmp_path / "missing.sqlite"
    watcher = fw.ForwardWatcher(missing, notifier())
    assert watcher.poll() is None
    assert not missing.exists() and not watcher.state_path.exists()


def test_temporary_sqlite_failure_does_not_advance(db, monkeypatch):
    watcher = fw.ForwardWatcher(db, notifier())
    watcher.poll()
    add(db)
    real = fw.journal

    @contextmanager
    def locked(path):
        raise sqlite3.OperationalError("database is locked")
        yield

    monkeypatch.setattr(fw, "journal", locked)
    assert watcher.poll() is None and watcher.cursor == 0
    monkeypatch.setattr(fw, "journal", real)
    assert watcher.poll() == 1 and watcher.cursor == 1


def test_failed_delivery_is_recorded_and_next_event_continues(db):
    add(db)
    add(db)
    sender = notifier()
    sender.send.side_effect = [Delivery("server_error", 3), Delivery("sent", 1)]
    watcher = fw.ForwardWatcher(db, sender, replay_last=2)
    assert watcher.poll() == 2 and watcher.cursor == 2
    assert watcher.state["failures"] == [{"rowid": 1, "status": "server_error", "attempts": 3}]
    assert fw.ForwardWatcher(db, sender).poll() == 0


def test_pending_interruption_is_not_resent(db):
    add(db)
    sender = notifier()
    sender.send.side_effect = KeyboardInterrupt
    watcher = fw.ForwardWatcher(db, sender, replay_last=1)
    with pytest.raises(KeyboardInterrupt):
        watcher.poll()
    assert watcher.cursor == 0 and watcher.state["pending"]["rowid"] == 1
    restarted = fw.ForwardWatcher(db, notifier())
    assert restarted.poll() == 0 and restarted.cursor == 1
    restarted.notifier.send.assert_not_called()
    assert restarted.state["failures"][-1]["status"] == "interrupted_unknown"


def test_atomic_save_failure_preserves_state_and_prevents_send(db, monkeypatch):
    watcher = fw.ForwardWatcher(db, notifier())
    watcher.poll()
    original = watcher.state_path.read_bytes()
    add(db)
    monkeypatch.setattr(fw.os, "replace", Mock(side_effect=PermissionError))
    with pytest.raises(PermissionError):
        watcher.poll()
    assert watcher.state_path.read_bytes() == original
    assert list(db.parent.glob(watcher.state_path.name + ".*")) == []
    watcher.notifier.send.assert_not_called()


def test_delivered_but_final_save_fails_is_not_resent(db, monkeypatch):
    add(db)
    sender = notifier()
    original = fw.atomic_state

    def save(path, state):
        if state["cursor"] == 1 and state["pending"] is None:
            raise PermissionError
        original(path, state)

    monkeypatch.setattr(fw, "atomic_state", save)
    watcher = fw.ForwardWatcher(db, sender, replay_last=1)
    with pytest.raises(PermissionError):
        watcher.poll()
    sender.send.assert_called_once()
    monkeypatch.setattr(fw, "atomic_state", original)
    assert fw.ForwardWatcher(db, sender).poll() == 0
    sender.send.assert_called_once()


def test_failure_history_is_bounded(db):
    with sqlite3.connect(db) as conn:
        conn.executemany(
            "INSERT INTO events VALUES ('s',?,'session',?)",
            [(str(i), json.dumps(SIGNAL)) for i in range(110)],
        )
    sender = Mock(send=Mock(return_value=Delivery("rejected", 1)))
    watcher = fw.ForwardWatcher(db, sender, replay_last=110)
    assert watcher.poll() == 110
    assert len(watcher.state["failures"]) == 100
    assert watcher.state["failures"][0]["rowid"] == 11


def test_corrupt_state_and_replaced_database_fail_closed(db):
    add(db)
    watcher = fw.ForwardWatcher(db, notifier())
    watcher.poll()
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE events SET stream='replaced'")
    with pytest.raises(ValueError, match="replaced/truncated"):
        fw.ForwardWatcher(db, notifier()).poll()
    watcher.state_path.write_text("broken", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid watcher state"):
        fw.ForwardWatcher(db, notifier())


def test_unknown_session_and_invalid_event_do_not_block(db):
    add(db, session="missing")
    add(db, ["not a payload object"])
    add(db)
    sender = notifier()
    watcher = fw.ForwardWatcher(db, sender, replay_last=3)
    assert watcher.poll() == 3
    assert sender.send.call_count == 1
    assert [f["status"] for f in watcher.state["failures"]] == [
        "unsupported_session",
        "invalid_event",
    ]


def test_dry_run_ignores_live_cursor_does_not_write_or_call_http(db, monkeypatch, capsys):
    add(db)
    watcher = fw.ForwardWatcher(db, notifier())
    watcher.poll()
    before = watcher.state_path.read_bytes()
    monkeypatch.setattr(TelegramNotifier, "send", Mock(side_effect=AssertionError("network")))
    assert fw.main(["--db", str(db), "--dry-run", "--replay-last", "3", "--once"]) == 0
    assert "SIGNAL GENERATED" in capsys.readouterr().out
    assert watcher.state_path.read_bytes() == before
    assert not watcher.lock_path.exists()


def test_cli_environment_absent_disabled_or_invalid(db, monkeypatch, caplog):
    assert fw.main(["--db", str(db), "--once"]) == 0
    monkeypatch.setenv("TELEGRAM_NOTIFICATIONS_ENABLED", "true")
    assert fw.main(["--db", str(db), "--once"]) == 2
    assert "TELEGRAM_BOT_TOKEN" in caplog.text
    assert not fw.ForwardWatcher(db).state_path.exists()


def test_invalid_poll_environment_never_echoes_value(monkeypatch, caplog):
    monkeypatch.setenv("TELEGRAM_POLL_SECONDS", "private-invalid-value")
    assert fw.main(["--dry-run", "--once"]) == 2
    assert "private-invalid-value" not in caplog.text


def test_long_payload_preserves_hypothetical_notice():
    message = format_event(
        {
            "kind": "ORDER_INTENT_CREATED",
            "strategy": "s" * 2000,
            "reference_price": "x" * 2000,
            "reason": "x" * 5000,
        },
        "session",
    )
    assert "SIGNAL ONLY — NOT sent to OKX" in message
    assert len(message.encode("utf-16-le")) // 2 < 4096


def test_once_drains_multiple_batches_without_live_cursor(db, capsys):
    with sqlite3.connect(db) as conn:
        conn.executemany(
            "INSERT INTO events VALUES ('s',?,'session',?)",
            [(str(i), json.dumps(SIGNAL)) for i in range(205)],
        )
    assert fw.main(["--db", str(db), "--dry-run", "--replay-last", "205", "--once"]) == 0
    assert capsys.readouterr().out.count("SIGNAL GENERATED") == 205


class Response(io.BytesIO):
    status = 200


def http_error(code, payload=None):
    return HTTPError(
        "https://redacted.invalid",
        code,
        "error",
        {},
        io.BytesIO(json.dumps(payload or {}).encode()),
    )


def client(effects):
    opener, sleep = Mock(), Mock()
    opener.open.side_effect = effects
    return (
        TelegramNotifier("12345:dummy_test_token", "dummy-chat", opener=opener, sleep=sleep),
        opener,
        sleep,
    )


def test_http_success_explicit_timeout_json_and_no_parse_mode():
    sender, opener, _ = client([Response(b'{"ok":true}')])
    assert sender.send("plain text") == Delivery("sent", 1)
    request = opener.open.call_args.args[0]
    assert opener.open.call_args.kwargs["timeout"] == 10
    assert request.get_method() == "POST"
    assert json.loads(request.data)["text"] == "plain text"
    assert "parse_mode" not in json.loads(request.data)
    assert NoRedirect().redirect_request(None, None, 302, "", {}, "https://other") is None


@pytest.mark.parametrize("failure", [TimeoutError, ConnectionError, URLError("offline")])
def test_http_transport_retries_are_bounded(failure, caplog):
    sender, opener, sleep = client([failure] * 3)
    assert sender.send("message") == Delivery("transport_unknown", 3)
    assert opener.open.call_count == 3 and sleep.call_count == 2
    assert "dummy_test_token" not in caplog.text


@pytest.mark.parametrize("code", [500, 502, 503])
def test_http_server_retry_then_success(code):
    sender, opener, sleep = client([http_error(code), Response(b'{"ok":true}')])
    assert sender.send("message") == Delivery("sent", 2)
    sleep.assert_called_once_with(1)


def test_http_429_retry_after_and_long_cooldown():
    sender, _, sleep = client(
        [http_error(429, {"parameters": {"retry_after": 3}}), Response(b'{"ok":true}')]
    )
    assert sender.send("message").status == "sent"
    sleep.assert_called_once_with(3)
    sender, opener, sleep = client([http_error(429, {"parameters": {"retry_after": 120}})])
    assert sender.send("message").status == "rate_limited"
    assert sender.send("next").attempts == 0
    assert opener.open.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize(
    "response",
    [http_error(401), http_error(403), http_error(302), Response(b'{"ok":false,"error_code":400}')],
)
def test_http_rejection_not_retried(response):
    sender, opener, _ = client([response])
    assert sender.send("message").status == "rejected"
    assert opener.open.call_count == 1


def test_missing_credentials():
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        TelegramNotifier.from_environment()


def test_own_lock_excludes_second_observer_and_releases(tmp_path):
    import subprocess
    import sys

    path = tmp_path / "observer.lock"
    command = [
        sys.executable,
        "-c",
        "from pathlib import Path; "
        "from quant_lab.notifications.forward_watcher import observer_lock; "
        f"\nwith observer_lock(Path({str(path)!r})): pass",
    ]
    with fw.observer_lock(path):
        assert subprocess.run(command, capture_output=True).returncode != 0
    assert subprocess.run(command, capture_output=True).returncode == 0


def test_cli_interrupt_exits_and_releases_lock(db, monkeypatch):
    monkeypatch.setenv("TELEGRAM_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setattr(TelegramNotifier, "from_environment", lambda: notifier())
    monkeypatch.setattr(fw.ForwardWatcher, "poll", Mock(side_effect=KeyboardInterrupt))
    assert fw.main(["--db", str(db)]) == 0
    with fw.observer_lock(fw.ForwardWatcher(db).lock_path):
        pass


def test_startup_once_after_retry(db, monkeypatch):
    sender = notifier()
    calls = iter([None, 0, 0])
    monkeypatch.setattr(fw.ForwardWatcher, "poll", lambda *a, **kw: next(calls))
    sleeps = Mock(side_effect=[None, None, KeyboardInterrupt])
    monkeypatch.setattr(fw.time, "sleep", sleeps)
    args = SimpleNamespace(
        dry_run=False, replay_last=None, include_rejected=False, once=False, startup_message=True
    )
    with pytest.raises(KeyboardInterrupt):
        fw.watch(args, db, sender, 2)
    sender.send.assert_called_once()


def test_no_notification_imports_in_forward_or_strategy():
    root = Path(__file__).resolve().parents[2] / "src/quant_lab"
    for folder in ("forward", "brokers", "strategies"):
        assert all(
            "quant_lab.notifications" not in p.read_text(encoding="utf-8")
            for p in (root / folder).glob("*.py")
        )
