"""Observer compatibility with the real Store; only temporary synthetic journals."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

from quant_lab.forward.config import load_config
from quant_lab.forward.runner import DEFAULT_CONFIG
from quant_lab.forward.store import Store
from quant_lab.notifications.forward_watcher import ForwardWatcher
from quant_lab.notifications.telegram import Delivery


def test_real_store_wal_sessions_streams_and_in_place_recovery(tmp_path):
    config, _, _ = load_config(DEFAULT_CONFIG)
    resolved = {"forward": config.model_dump(mode="json")}
    sender = Mock(send=Mock(return_value=Delivery("sent", 1)))
    watcher = ForwardWatcher(tmp_path / "forward.sqlite", sender)
    # A runner can start after the observer; the missing DB must not be created by it.
    assert watcher.poll() is None
    first = Store(tmp_path, resolved, {"code_sha256": "fixture-version-1"})
    try:
        with first.db:
            first.event("HEARTBEAT", "history", {})
        assert watcher.poll() == 0
        with first.db:
            first.event("SIGNAL_GENERATED", "signal-1", {"signal_id": "signal-1"})
        assert watcher.poll() == 1
        with first.db:
            first.event("DATA_GAP", "gap-1", {"resolved": False, "reason": "disconnected"})
        watcher.poll()
        gap = first.gaps()[0]
        with first.db:
            first.update_gap(gap, resolved=True)
            first.event("DATA_GAP_RESOLVED", "gap-1", {"resolved": True})
        assert watcher.poll() == 1
        assert "DATA GAP RESOLVED" in sender.send.call_args.args[0]
        assert first.db.execute("SELECT COUNT(*) FROM orders").fetchone() == (0,)
        assert first.db.execute("SELECT COUNT(*) FROM fills").fetchone() == (0,)
    finally:
        first.close()
    second = Store(tmp_path, resolved, {"code_sha256": "fixture-version-2"})
    try:
        with second.db:
            second.event("SIGNAL_GENERATED", "signal-2", {"signal_id": "signal-2"})
        restarted = ForwardWatcher(tmp_path / "forward.sqlite", sender)
        assert restarted.poll() == 1
        assert sender.send.call_count == 4
        assert restarted.poll() == 0
        assert second.db.execute("PRAGMA journal_mode").fetchone() == ("wal",)
    finally:
        second.close()


def test_cli_from_other_directory_without_env_or_http(tmp_path):
    config, _, _ = load_config(DEFAULT_CONFIG)
    store = Store(tmp_path, {"forward": config.model_dump(mode="json")}, {"code_sha256": "fixture"})
    try:
        with store.db:
            store.event("SIGNAL_GENERATED", "one", {"signal_id": "one"})
        script = Path(__file__).resolve().parents[2] / "scripts/notification_watcher.py"
        env = {k: v for k, v in os.environ.items() if not k.startswith("TELEGRAM_")}
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import runpy, sys; from pathlib import Path; "
                "from quant_lab.notifications import forward_watcher as fw; "
                f"fw.ROOT=Path({str(tmp_path)!r}); "
                f"sys.argv[0]={str(script)!r}; runpy.run_path(sys.argv[0], run_name='__main__')",
                "--db",
                str(tmp_path / "forward.sqlite"),
                "--dry-run",
                "--replay-last",
                "3",
                "--once",
            ],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            encoding="utf-8",
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        assert "SIGNAL GENERATED" in result.stdout
        assert not list(tmp_path.glob("*telegram*"))
    finally:
        store.close()


def test_real_exclusive_lock_retries_without_state_loss(tmp_path):
    path = tmp_path / "locked.sqlite"
    writer = sqlite3.connect(path)
    writer.execute("CREATE TABLE events (stream TEXT,id TEXT,session TEXT,data TEXT)")
    writer.execute("CREATE TABLE sessions (id TEXT,data TEXT)")
    config, _, _ = load_config(DEFAULT_CONFIG)
    writer.execute(
        "INSERT INTO sessions VALUES ('s',?)",
        (json.dumps({"config": {"forward": config.model_dump(mode="json")}}),),
    )
    writer.commit()
    watcher = ForwardWatcher(path, Mock(send=Mock(return_value=Delivery("sent", 1))))
    watcher.poll()
    writer.execute("BEGIN EXCLUSIVE")
    writer.execute(
        "INSERT INTO events VALUES ('s','1','s',?)", (json.dumps({"kind": "SIGNAL_GENERATED"}),)
    )
    try:
        assert watcher.poll() is None and watcher.cursor == 0
    finally:
        writer.commit()
        writer.close()
    assert watcher.poll() == 1 and watcher.cursor == 1
