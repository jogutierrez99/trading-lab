"""Only our temporary children and controlled probes; never signal system processes."""

import json
import os
import sqlite3
import subprocess
import sys

import pytest

from trading_lab_orchestration import process_identity as identity
from trading_lab_orchestration.processes import run_process


@pytest.fixture
def child():
    p = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
    try:
        yield p
    finally:
        if p.poll() is None:
            p.kill()  # The fixture's original Popen handle, not an inspected PID.
        p.wait(timeout=10)


def test_original_live_then_exited(child):
    birth = identity.capture(child.pid)
    assert birth["pid"] == child.pid and isinstance(birth["created"], str)
    assert identity.identity_state(child.pid, birth) == "RUNNING"
    child.kill()
    child.wait(timeout=10)
    assert identity.identity_state(child.pid, birth) == "EXITED"


@pytest.mark.parametrize("case", ["reused", "denied", "missing", "malformed", "wrong_clock"])
def test_controlled_identity_checks_never_signal(child, monkeypatch, case):
    birth = identity.capture(child.pid)
    expected = dict(birth)
    current = dict(birth)
    if case == "reused":
        current["created"] = str(int(current["created"]) + 1)  # One native tick; no rounding.
    elif case == "denied":

        def denied(*args):
            raise PermissionError("controlled access denied")

        monkeypatch.setattr(identity, "_probe", denied)
    elif case == "missing":
        expected.pop("created")
    elif case == "malformed":
        expected["created"] = float(expected["created"])
    else:
        expected["clock"] = "unknown"
    if case != "denied":
        monkeypatch.setattr(identity, "_probe", lambda *args: (current, True))
    state = identity.identity_state(child.pid, expected)
    assert state == ("REUSED" if case == "reused" else "UNKNOWN")
    assert child.poll() is None
    assert identity.pending(
        {"child_pid": child.pid, "process_identity_json": json.dumps(expected)}
    ) == (case != "reused")


def test_legacy_absent_and_incomplete_remain_distinct(child, monkeypatch):
    assert identity.identity_state(child.pid) == "UNKNOWN"
    assert identity.pending({"status": "RUNNING", "child_pid": None})
    monkeypatch.setattr(identity, "_probe", lambda *args: None)
    assert identity.identity_state(child.pid) == "EXITED"
    assert identity.identity_state(None) == "NOT_RECORDED"


@pytest.mark.parametrize("timeout", [False, True])
def test_supervised_child_records_exact_birth_before_execution(tmp_path, child, timeout):
    started = []
    result = run_process(
        [sys.executable, "-c", "import time;time.sleep(30)" if timeout else "pass"],
        tmp_path,
        0.2 if timeout else 10,
        tmp_path / "stdout",
        tmp_path / "stderr",
        on_start=lambda birth: started.append(birth),
    )
    assert result["process_identity"] == started[0]
    assert result["pid"] == started[0]["pid"]
    assert result["timed_out"] == timeout
    assert identity.identity_state(result["pid"], started[0]) in {"EXITED", "REUSED"}
    assert child.poll() is None  # Unrelated temporary process survives cleanup.
    if os.name == "nt":
        assert started[0]["clock"] == "WINDOWS_FILETIME_100NS"


def test_schema_v6_readonly_and_migration_do_not_invent_identity(tmp_path):
    from trading_lab_orchestration.readonly import ReadOnlyStore
    from trading_lab_orchestration.store import Store

    store = Store(tmp_path / "legacy.sqlite3")
    with store.transaction() as c:
        for table in ("attempts", "executions", "manual_repairs"):
            c.execute("ALTER TABLE " + table + " DROP COLUMN process_identity_json")
        c.execute("PRAGMA user_version=6")
    before = store.path.read_bytes()
    with ReadOnlyStore(store.path).connection() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 6
    assert store.path.read_bytes() == before
    Store(store.path)
    with store.connection() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 7
        for table in ("attempts", "executions", "manual_repairs"):
            assert "process_identity_json" in {
                r[1] for r in c.execute("PRAGMA table_info(" + table + ")")
            }


def test_pending_accepts_native_sqlite_rows(child):
    birth = identity.capture(child.pid)
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT ? AS child_pid, ? AS process_identity_json, 'RUNNING' AS status",
            (child.pid, json.dumps(birth)),
        ).fetchone()
        assert identity.pending(row)


@pytest.mark.skipif(os.name != "nt", reason="Windows suspended-start guarantee")
def test_identity_is_persisted_before_windows_child_can_execute(tmp_path):
    def persist(birth):
        assert identity.identity_state(birth["pid"], birth) == "RUNNING"
        assert not (tmp_path / "executed").exists()
        (tmp_path / "birth.json").write_text(json.dumps(birth))

    result = run_process(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; assert Path('birth.json').is_file(); "
            "Path('executed').write_text('after persistence')",
        ],
        tmp_path,
        10,
        tmp_path / "stdout",
        tmp_path / "stderr",
        on_start=persist,
    )
    assert result["exit_code"] == 0
    assert json.loads((tmp_path / "birth.json").read_text()) == result["process_identity"]
    assert (tmp_path / "executed").is_file()
