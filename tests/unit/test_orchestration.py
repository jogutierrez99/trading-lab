"""Offline acceptance: real SQLite transactions, concurrency and separate CLI processes."""

import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier

import pytest
from pydantic import ValidationError

from trading_lab_orchestration.cli import main
from trading_lab_orchestration.contracts import HypothesisManifest, canonical, digest, load_manifest
from trading_lab_orchestration.store import Store, database_path

ROOT = Path(__file__).resolve().parents[2]
VALID = ROOT / "examples/orchestration/manual_valid.json"
INCOMPLETE = ROOT / "examples/orchestration/manual_incomplete.json"


@pytest.fixture
def payload():
    return json.loads(VALID.read_text())


def parse(payload):
    return HypothesisManifest.model_validate_json(json.dumps(payload))


def counts(path):
    with sqlite3.connect(path) as conn:
        return tuple(
            conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("candidates", "tasks", "events", "submissions")
        )


def test_valid_and_incomplete_without_database(tmp_path, capsys):
    db = tmp_path / "absent.sqlite3"
    assert main(["--db", str(db), "validate", str(VALID)]) == 0
    assert json.loads(capsys.readouterr().out)["valid"]
    assert main(["--db", str(db), "register", str(INCOMPLETE)]) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "INVALID_MANIFEST"
    assert not db.exists()


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": "2.0"},
        {"title": "   "},
        {"requires_new_strategy_code": "false"},
        {"capabilities": ["execute"]},
        {"created_at_utc": "2026-11-03T08:00:00"},
        {"created_at_utc": "2026-11-03T08:00:00+01:00"},
        {"status": "RESEARCH_PASS"},
        {"source_refs": []},
    ],
)
def test_invalid_contract(payload, change):
    payload.update(change)
    with pytest.raises(ValidationError):
        parse(payload)


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("execution_assumptions", "trading_fee_pct", -1),
        ("execution_assumptions", "spread_pct", float("nan")),
        ("execution_assumptions", "entry_timing", "SAME_CLOSE"),
        ("execution_assumptions", "hidden_permission", True),
        ("data_requirements", "funding_policy", "REQUIRED"),
        ("signal_spec", "short_entry", "short now"),
        ("signal_spec", "long_exit", None),
        ("parameter_space", "combination_limit", 0),
    ],
)
def test_nested_rejections(payload, section, key, value):
    payload[section][key] = value
    with pytest.raises(ValidationError):
        parse(payload)


def test_periods_and_grid(payload):
    payload["evaluation_plan"]["train"]["end"] = "2022-04-02T00:00:00Z"
    with pytest.raises(ValidationError, match="chronological"):
        parse(payload)
    payload["evaluation_plan"]["train"]["end"] = "2022-04-01T00:00:00Z"
    payload["parameter_space"]["parameters"]["entry_window"]["values"] = [20, 30]
    with pytest.raises(ValidationError, match="combination_limit"):
        parse(payload)


def test_json_duplicate_keys(tmp_path):
    source = tmp_path / "duplicate.json"
    source.write_text('{"schema_version":"1.0","schema_version":"2.0"}')
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        load_manifest(source)


def test_duplicate_variants_and_conflict(tmp_path, payload):
    store = Store(tmp_path / "coordinator.sqlite3")
    manifest = parse(payload)
    first = store.register(manifest)
    assert store.register(manifest)["candidate_id"] == first["candidate_id"]
    assert counts(store.path) == (1, 1, 4, 1)
    payload.update(hypothesis_id="alternate", title="Different title")
    duplicate = store.register(parse(payload))
    assert duplicate["duplicate"] and duplicate["task_id"] == first["task_id"]
    assert counts(store.path) == (1, 1, 5, 2)
    assert store.show("alternate")["candidate_id"] == first["candidate_id"]
    payload["signal_spec"]["long_entry"] += " Different rule."
    with pytest.raises(ValueError, match="different content"):
        store.register(parse(payload))
    assert counts(store.path) == (1, 1, 5, 2)
    payload["hypothesis_id"] = "new_rules_same_title"
    assert store.register(parse(payload))["created"]
    assert counts(store.path) == (2, 2, 8, 3)


def test_fingerprint_key_order_and_metadata(payload):
    manifest = parse(payload)
    reordered = json.loads(json.dumps(payload, sort_keys=True))
    assert parse(reordered).snapshot() == manifest.snapshot()
    reordered["created_at_utc"] = "2026-11-04T08:00:00Z"
    reordered["hypothesis_id"] = "another"
    assert parse(reordered).fingerprint() == manifest.fingerprint()
    reordered["execution_assumptions"]["slippage_pct"] = 0.06
    assert parse(reordered).fingerprint() != manifest.fingerprint()


@pytest.mark.parametrize("alternate_ids", [False, True])
def test_simultaneous_registration_and_initialization(tmp_path, payload, alternate_ids):
    path = tmp_path / "concurrent.sqlite3"
    barrier = Barrier(6)

    def register(index):
        data = deepcopy(payload)
        if alternate_ids:
            data["hypothesis_id"] = f"concurrent_{index}"
        barrier.wait(timeout=10)
        return Store(path).register(parse(data))

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(register, range(6)))
    assert sum(item["created"] for item in results) == 1
    assert len({item["task_id"] for item in results}) == 1
    assert counts(path) == (1, 1, 8, 6 if alternate_ids else 1)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("failure_table", ["tasks", "submissions", "events"])
def test_atomic_registration_failure(tmp_path, failure_table):
    store = Store(tmp_path / "atomic.sqlite3")
    with sqlite3.connect(store.path) as conn:
        conn.execute(f"""CREATE TRIGGER injected_failure BEFORE INSERT ON {failure_table}
                         BEGIN SELECT RAISE(ABORT,'injected failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        store.register(load_manifest(VALID))
    assert counts(store.path) == (0, 0, 0, 0)
    with sqlite3.connect(store.path) as conn:
        conn.execute("DROP TRIGGER injected_failure")
    assert Store(store.path).register(load_manifest(VALID))["created"]


def test_states_atomic_and_immutable(tmp_path):
    store = Store(tmp_path / "states.sqlite3")
    candidate = store.register(load_manifest(VALID))["candidate_id"]
    store.transition(candidate, "HYPOTHESIS_READY", "BLOCKED", "Missing dataset")
    state = Store(store.path).show(candidate)
    assert state["status"] == state["task"]["status"] == "BLOCKED"
    with pytest.raises(ValueError, match="stale"):
        store.transition(candidate, "HYPOTHESIS_READY", "CANCELLED", "stale client")
    with pytest.raises(ValueError, match="not allowed"):
        store.transition(candidate, "BLOCKED", "BACKTEST_RUNNING", "unauthorized")
    with sqlite3.connect(store.path) as conn:
        conn.execute("""CREATE TRIGGER injected_failure BEFORE INSERT ON events
                        BEGIN SELECT RAISE(ABORT,'injected'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        store.transition(candidate, "BLOCKED", "HYPOTHESIS_READY", "Clarified")
    assert store.show(candidate)["status"] == "BLOCKED"
    with sqlite3.connect(store.path) as conn:
        for sql in ("UPDATE candidates SET manifest_json='{}'", "DELETE FROM events"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                conn.execute(sql)
    snapshot = state["manifest"]
    assert digest(canonical(snapshot)) == state["manifest_sha256"]
    for event in state["events"]:
        assert digest(event["payload_json"]) == event["payload_sha256"]


def test_foreign_database_and_future_version_rejected(tmp_path):
    path = tmp_path / "experiments.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE experiments(id INTEGER)")
    original = path.read_bytes()
    with pytest.raises(ValueError, match="refusing"):
        Store(path)
    assert path.read_bytes() == original
    path = tmp_path / "future.sqlite3"
    Store(path)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="refusing"):
        Store(path)


def test_cli_persistence_across_processes(tmp_path):
    db = tmp_path / "cli.sqlite3"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}

    def run(*args):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/orchestrator.py"), "--db", str(db), *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=ROOT,
            timeout=20,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    first = run("register", str(VALID))
    assert run("register", str(VALID))["task_id"] == first["task_id"]
    assert run("list")["candidates"][0]["status"] == "HYPOTHESIS_READY"
    assert run("show", first["task_id"])["candidate_id"] == first["candidate_id"]
    run(
        "transition",
        first["candidate_id"],
        "--from",
        "HYPOTHESIS_READY",
        "--to",
        "BLOCKED",
        "--reason",
        "Data pending",
    )
    assert run("show", "manual_example_001")["task"]["status"] == "BLOCKED"
    assert run("register", str(VALID))["status"] == "BLOCKED"


def test_database_path_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_LAB_ORCHESTRATOR_DB", str(tmp_path / "env.sqlite3"))
    assert database_path() == tmp_path / "env.sqlite3"
    assert database_path(str(tmp_path / "explicit.sqlite3")) == tmp_path / "explicit.sqlite3"
    monkeypatch.delenv("TRADING_LAB_ORCHESTRATOR_DB")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert database_path() == tmp_path / "TradingLab/orchestration/orchestrator.sqlite3"


@pytest.mark.parametrize("initialized", [False, True])
def test_two_processes_register_same_manifest(tmp_path, initialized):
    """Release two independent interpreters together, including first-start DDL."""
    db = tmp_path / "two-processes.sqlite3"
    if initialized:
        Store(db)
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    child = """
import json, os, sys
from trading_lab_orchestration.cli import main
print(json.dumps({'ready_pid': os.getpid()}), flush=True)
assert sys.stdin.readline().strip() == 'GO'
raise SystemExit(main(sys.argv[1:]))
"""
    processes = []
    results = []
    pids = []
    try:
        for _ in range(2):
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-u", "-c", child, "--db", str(db), "register", str(VALID)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=ROOT,
                    env=env,
                )
            )
        for process in processes:
            ready = process.stdout.readline()
            assert ready, "Child exited before ready barrier"
            pids.append(json.loads(ready)["ready_pid"])
        assert len(set(pids)) == 2
        for process in processes:
            process.stdin.write("GO\n")
            process.stdin.flush()
        for process in processes:
            stdout, stderr = process.communicate(timeout=25)
            assert process.returncode == 0, stdout + stderr
            assert not stderr
            results.append(json.loads(stdout))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
    assert sum(result["created"] for result in results) == 1
    assert sum(result["duplicate"] for result in results) == 1
    assert len({result["candidate_id"] for result in results}) == 1
    assert len({result["task_id"] for result in results}) == 1
    assert counts(db) == (1, 1, 4, 1)
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        candidate, task = conn.execute("SELECT candidate_id,task_id FROM tasks").fetchone()
    assert all(
        result["candidate_id"] == candidate and result["task_id"] == task for result in results
    )
    print(
        canonical(
            {
                "case": "two_processes",
                "initialized": initialized,
                "pids": pids,
                "exit_codes": [p.returncode for p in processes],
                "results": results,
                "counts_candidates_tasks_events_submissions": counts(db),
                "integrity_check": "ok",
                "foreign_key_check": [],
            }
        )
    )


@pytest.mark.parametrize("seeded", [False, True])
def test_cli_failure_after_partial_writes_rolls_back(tmp_path, payload, seeded):
    """Fail the second event after candidate, task, submission and first event exist."""
    db = tmp_path / "rollback.sqlite3"
    store = Store(db)
    if seeded:
        payload["hypothesis_id"] = "preserved_candidate"
        payload["market_hypothesis"] = "Separate existing specification"
        store.register(parse(payload))

    def rows():
        with sqlite3.connect(db) as conn:
            return {
                table: conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                for table in ("candidates", "tasks", "events", "submissions")
            }

    before = rows()
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TRIGGER injected_late_failure BEFORE INSERT ON events
            WHEN NEW.new_state='HYPOTHESIS_READY' AND EXISTS
                (SELECT 1 FROM candidates WHERE candidate_id=NEW.candidate_id
                 AND hypothesis_id='manual_example_001')
            BEGIN
                SELECT CASE WHEN
                    (SELECT count(*) FROM tasks WHERE candidate_id=NEW.candidate_id)=1
                    AND (SELECT count(*) FROM submissions
                         WHERE candidate_id=NEW.candidate_id)=1
                    AND (SELECT count(*) FROM events WHERE candidate_id=NEW.candidate_id)=1
                THEN RAISE(ABORT,'injected after partial writes')
                ELSE RAISE(ABORT,'unexpected injection point') END;
            END""")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    argv = [
        sys.executable,
        str(ROOT / "scripts/orchestrator.py"),
        "--db",
        str(db),
        "register",
        str(VALID),
    ]
    failed = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT, env=env, timeout=25)
    assert failed.returncode == 2
    assert not failed.stderr
    error = json.loads(failed.stdout)
    assert error == {"error": "IntegrityError", "message": "injected after partial writes"}
    assert rows() == before  # No partial rows; pre-existing data identical, including events.
    after_failure = counts(db)
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TRIGGER injected_late_failure")
    retry = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT, env=env, timeout=25)
    assert retry.returncode == 0, retry.stdout + retry.stderr
    result = json.loads(retry.stdout)
    assert result["created"] and not result["duplicate"]
    baseline = int(seeded)
    assert counts(db) == (baseline + 1, baseline + 1, baseline * 3 + 3, baseline + 1)
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    print(
        canonical(
            {
                "case": "late_transaction_failure",
                "seeded": seeded,
                "failure_exit_code": failed.returncode,
                "handled_error": error,
                "counts_after_failure": after_failure,
                "prior_rows_unchanged": True,
                "retry_exit_code": retry.returncode,
                "retry": result,
                "counts_after_retry": counts(db),
                "integrity_check": "ok",
            }
        )
    )
