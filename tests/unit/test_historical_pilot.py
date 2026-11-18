"""5.5B synthetic-only regression matrix. No operational permit or historical execution."""

import base64
import json
import os
import random
import sqlite3
import zlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from trading_lab_orchestration import historical_pilot as host
from trading_lab_orchestration import historical_pilot_store as store
from trading_lab_orchestration.contracts import canonical
from trading_lab_orchestration.historical_pilot_contract import (
    CANDLES,
    MAX_WIRE,
    BlockedDataset,
    Job,
    candles_bytes,
    decode_transport,
    encode_transport,
    hash_bytes,
    plan_sha,
    preflight_dataset,
    read_candles,
    validate_frame,
)
from trading_lab_orchestration.historical_pilot_guest import calculate
from trading_lab_orchestration.historical_pilot_oracle import crossings, protective
from trading_lab_orchestration.isolated_study_contract import (
    IMAGE,
    PILOT_DATASET,
    SemanticInconsistency,
)
from trading_lab_orchestration.pilot_launch import DDL
from trading_lab_orchestration.verification_container import (
    IsolationUnavailable,
    IsolationUncertain,
    VerificationContainer,
    _payload,
)


@pytest.fixture(scope="module")
def synthetic():
    job, files, _ = host.prepare(SimpleNamespace(image=IMAGE, fingerprint="1" * 64))
    frame = read_candles(files[CANDLES], job)
    cases = [calculate(frame, job, case) for case in job.plan.cases]
    return job, files, frame, cases, encode_transport(job, cases)


def test_six_cases_account_for_every_trade(synthetic):
    job, files, _, cases, wire = synthetic
    assert len(wire) < MAX_WIRE
    assert [len(case["trades"]) for case in cases] == [7, 7, 4, 4, 3, 3]
    assert job.plan.holdout == "CONSUMED" and job.mode == "SYNTHETIC"
    audit = host._audit(job, files[CANDLES], wire)
    assert audit["sample_sizes"] == [7, 7, 4, 4, 3, 3]
    assert audit["economic_decision"] == "NO_DECISION"
    assert all(item["fees_paid"][1] > item["fees_paid"][0] for item in audit["comparison"].values())


def test_full_windows_with_dense_artificial_trades(synthetic):
    job, _, frame, _, _ = synthetic
    frame = frame.astype(float)
    rng = random.Random(553)
    levels = [1000 + rng.uniform(-50, 50) for _ in frame.index]
    frame["open"] = frame["close"] = levels
    frame["high"] = [x + 0.1 + rng.random() for x in levels]
    frame["low"] = [x - 0.1 - rng.random() for x in levels]
    payload = candles_bytes(frame, job.plan.cases)
    checksum = hash_bytes(payload)
    job = Job.model_validate_json(
        job.model_copy(
            update={
                "candles_sha256": checksum,
                "closure": job.closure | {CANDLES: checksum},
            }
        ).model_dump_json()
    )
    cases = [calculate(frame, job, case) for case in job.plan.cases]
    wire = encode_transport(job, cases)
    assert 80 * 1024 < len(wire) < MAX_WIRE
    assert host._audit(job, payload, wire)["sample_sizes"] == [48, 48, 20, 20, 23, 23]


@pytest.mark.parametrize(
    "bad", ["gap", "duplicate", "unordered", "ohlcv", "nan", "inf", "warmup", "date", "timezone"]
)
def test_invalid_ohlcv_and_coverage(synthetic, bad):
    job, _, frame, _, _ = synthetic
    broken = frame.copy()
    if bad == "gap":
        broken = broken.drop(broken.index[250])
    elif bad == "duplicate":
        broken = pd.concat([broken.iloc[:1], broken])
    elif bad == "unordered":
        broken = broken.iloc[::-1]
    elif bad == "ohlcv":
        broken.iloc[250, 1] = 1
    elif bad in {"nan", "inf"}:
        broken = broken.astype(float)
        broken.iloc[250, 4] = float(bad)
    elif bad == "warmup":
        broken = broken.iloc[1:]
    elif bad == "date":
        broken.index += pd.Timedelta(days=365)
    else:
        broken.index = broken.index.tz_localize(None)
    with pytest.raises(BlockedDataset, match="BLOCKED_DATASET"):
        validate_frame(broken, job.plan.cases)


def test_dataset_missing_and_hash_mismatch(tmp_path, synthetic):
    job, *_ = synthetic
    with pytest.raises(BlockedDataset, match="unavailable"):
        preflight_dataset(tmp_path, job.plan.cases)
    dataset = tmp_path / "data/history" / PILOT_DATASET
    dataset.mkdir(parents=True)
    (dataset / "candles.parquet").write_bytes(b"Different dataset")
    (dataset / "manifest.json").write_bytes(b"{}")
    with pytest.raises(BlockedDataset, match="SHA-256"):
        preflight_dataset(tmp_path, job.plan.cases)


def test_independent_crossings_are_prefix_causal():
    closes = [100.0] * 220 + [101.0] * 5 + [80.0] * 5
    signals = list(crossings(closes))
    assert signals[220] == (True, False)
    assert any(sell for _, sell in signals[225:])
    assert list(crossings(closes[:224])) == signals[:224]
    assert not any(t for pair in crossings([100.0] * 250) for t in pair)


@pytest.mark.parametrize(
    ("bar", "signal", "last", "expected"),
    [
        ((90, 120, 80, 100, 1), True, False, "stop_gap"),
        ((120, 130, 90, 110, 1), True, False, "target_gap"),
        ((100, 120, 90, 100, 1), False, False, "stop"),
        ((100, 120, 99, 100, 1), False, False, "target"),
        ((100, 105, 99, 103, 1), True, True, "signal"),
        ((100, 105, 99, 103, 1), False, True, "end_of_study"),
    ],
)
def test_independent_exit_priority(bar, signal, last, expected):
    assert protective(bar, 95, 110, signal=signal, last=last)[1] == expected


@pytest.mark.parametrize(
    "attack", ["missing", "added", "moved", "exit", "fees", "equity", "exposure", "pnl", "metric"]
)
def test_resealed_economic_attack_rejected(synthetic, attack):
    job, files, _, cases, _ = synthetic
    changed = deepcopy(cases)
    case = changed[0]
    trade = case["trades"][0]
    if attack == "missing":
        # Accounting-consistent omission: a flat case, including metrics and exposure.
        case["trades"] = []
        case["equity"] = [job.plan.risk.initial_cash] * len(case["equity"])
        case["exposure"] = [0] * len(case["exposure"])
        case["metrics"] = {
            key: None if key in {"expectancy", "profit_factor", "win_rate_pct"} else 0
            for key in case["metrics"]
        }
    elif attack == "added":
        case["trades"].append(dict(trade))
    elif attack == "moved":
        trade["entry_time"] = job.plan.cases[0].start.isoformat()
    elif attack == "exit":
        trade["reason"] = "signal"
    elif attack == "fees":
        trade["entry_fee"] += 0.01
    elif attack == "equity":
        case["equity"][1] += 100
    elif attack == "exposure":
        case["exposure"][1] = 0.2
    elif attack == "pnl":
        trade["net_pnl"] += 0.01
    elif attack == "metric":
        case["metrics"]["expectancy"] += 1
    with pytest.raises(SemanticInconsistency):
        host._audit(job, files[CANDLES], encode_transport(job, changed))


@pytest.mark.parametrize(
    "attack",
    [
        "exact",
        "above",
        "truncated",
        "duplicate",
        "count",
        "order",
        "hash",
        "extra",
        "nonfinite",
        "trailing_zlib",
    ],
)
def test_transport_rejects_malformed_or_unsealed_parts(synthetic, attack):
    job, _, _, _, wire = synthetic
    document = json.loads(wire)
    if attack in {"exact", "above"}:
        length = MAX_WIRE + (attack == "above")
        wire += b" " * (length - len(wire))
    elif attack == "truncated":
        wire = wire[:-3]
    elif attack == "duplicate":
        wire = wire.replace(b'{"job_sha256"', b'{"schema_version":"1.0","job_sha256"', 1)
    else:
        part = document["parts"][0]
        if attack == "count":
            document["parts"].pop()
        elif attack == "order":
            document["parts"].reverse()
        elif attack == "hash":
            part["sha256"] = "0" * 64
        elif attack == "extra":
            part["unexpected"] = True
        elif attack == "nonfinite":
            raw = zlib.decompress(base64.b64decode(part["zlib"])).replace(
                b'"equity":[', b'"equity":[NaN,', 1
            )
            part.update(
                size=len(raw),
                sha256=hash_bytes(raw),
                zlib=base64.b64encode(zlib.compress(raw)).decode(),
            )
        else:
            part["zlib"] = base64.b64encode(base64.b64decode(part["zlib"]) + b"garbage").decode()
        wire = canonical(document).encode()
    with pytest.raises(ValueError):
        list(decode_transport(wire, job))


def test_valid_wire_just_below_limit(synthetic):
    job, _, _, _, wire = synthetic
    assert len(list(decode_transport(wire + b" " * (MAX_WIRE - len(wire) - 1), job))) == 6


@pytest.fixture
def permit_db(tmp_path, synthetic):
    job, *_ = synthetic
    database = tmp_path / host.DB
    store.initialize(database)
    permit = store.Permit(
        purpose="SYNTHETIC_BACKTEST_ONCE",
        attempt_id="attempt_" + "0" * 32,
        implementation_receipt_sha256="0" * 64,
        job_sha256=plan_sha(job),
        operator="temporary-fixture",
        operator_sid="S-1-0-0",
        approved_at=datetime.now(UTC),
    )
    return database, permit


def test_permission_required_and_plan_bound(permit_db):
    database, permit = permit_db
    with pytest.raises(ValueError, match="match"):
        store.grant(database, permit, "yes")
    with pytest.raises(ValueError, match="required"):
        store.reserve(database, "0" * 64, permit.job_sha256, permit.purpose, "dir")
    key = store.grant(database, permit, store.phrase(permit))
    with pytest.raises(ValueError, match="scope"):
        store.reserve(database, key, "0" * 64, permit.purpose, "dir")
    with pytest.raises(ValueError, match="scope"):
        store.reserve(database, key, permit.job_sha256, "HISTORICAL_BACKTEST_ONCE", "dir")
    assert store.reserve(database, key, permit.job_sha256, permit.purpose, "dir")[0]


def test_historical_permit_requires_verified_operator_and_attempt_binding(permit_db):
    database, original = permit_db
    permit = store.Permit.model_validate_json(
        original.model_copy(
            update={"purpose": "HISTORICAL_BACKTEST_ONCE"},
        ).model_dump_json()
    )
    args = (
        database,
        store.grant(database, permit, store.phrase(permit)),
        permit.job_sha256,
        permit.purpose,
        "dir",
    )
    with pytest.raises(ValueError, match="Windows operator"):
        store.reserve(*args)
    with store.transaction(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_reservation_is_atomic_and_never_rearmed(permit_db):
    database, permit = permit_db
    key = store.grant(database, permit, store.phrase(permit))
    with ThreadPoolExecutor(2) as callers:
        results = list(
            callers.map(
                lambda _: store.reserve(database, key, permit.job_sha256, permit.purpose, "id"),
                range(2),
            )
        )
    assert sorted(result[0] for result in results) == [False, True]
    store.bind_job(database, key, "folder")
    store.finish(database, key)
    assert store.reserve(database, key, permit.job_sha256, permit.purpose, "id") == (
        False,
        ("folder", "UNKNOWN", None),
    )
    with pytest.raises(ValueError, match="different scratch"):
        store.reserve(database, key, permit.job_sha256, permit.purpose, "replacement")
    with pytest.raises(sqlite3.IntegrityError, match="consumed"):
        with store.transaction(database) as conn:
            conn.execute("DELETE FROM runs")
    with pytest.raises(sqlite3.IntegrityError, match="already exists"):
        store.grant(database, permit, store.phrase(permit))


def test_legacy_trigger_still_rejects_even_with_separate_permit(permit_db):
    database, permit = permit_db
    store.grant(database, permit, store.phrase(permit))
    guard = next(item for item in DDL if "TRIGGER IF NOT EXISTS pilot_launch_no_backtest" in item)
    with sqlite3.connect(":memory:") as conn:
        conn.executescript(
            "CREATE TABLE executions(attempt_id);CREATE TABLE pilot_authorizations(attempt_id);"
        )
        conn.execute(guard)
        conn.execute("INSERT INTO pilot_authorizations VALUES (?)", (permit.attempt_id,))
        with pytest.raises(sqlite3.IntegrityError, match="separate backtest authorization"):
            conn.execute("INSERT INTO executions VALUES (?)", (permit.attempt_id,))


@pytest.mark.parametrize(
    "interruption",
    [None, "before_docker_returns", "before_publish", "preflight", "timeout", "cleanup", "capture"],
)
def test_coordinator_replays_or_stops_without_second_docker(
    tmp_path, synthetic, permit_db, monkeypatch, interruption
):
    job, files, _, _, wire = synthetic
    db, permit = permit_db
    key = store.grant(db, permit, store.phrase(permit))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    starts = []

    @contextmanager
    def directory(path, *, fresh=False, occupy=False):
        if fresh:
            path.mkdir()
        assert path.is_dir()
        yield

    def publish(path, raw, limit):
        if interruption == "before_publish":
            raise KeyboardInterrupt
        with path.open("xb") as handle:
            handle.write(raw)

    class Verifier:
        _ok = staticmethod(host.VerificationContainer._ok)

        def preflight(self, **kwargs):
            if interruption == "preflight":
                raise IsolationUnavailable("synthetic preflight failure")
            return {"probe": ["ISOLATION_PROBE_OK"]}

        def _execute(self, command, stdin, folder, name, timeout, *, stdout_capture_limit):
            starts.append(command)
            assert stdout_capture_limit == MAX_WIRE
            if interruption == "before_docker_returns":
                raise KeyboardInterrupt
            result = {"exit_code": 0, "timed_out": False, "output_truncated": False}
            (folder / "historical-cleanup.json").write_text(
                canonical(
                    result | {"exit_code": 1 if interruption == "cleanup" else 0},
                )
            )
            (folder / "historical.stdout").write_bytes(b"substituted diagnostic")
            return result | {
                "stdout_bytes": None if interruption == "capture" else wire,
                "duration_seconds": 0.01,
                "timed_out": interruption == "timeout",
            }

    monkeypatch.setattr(host.ntfs, "directory", directory)
    monkeypatch.setattr(
        host.ntfs, "directory_identity", lambda p: [p.stat().st_dev, p.stat().st_ino]
    )
    monkeypatch.setattr(host.ntfs, "publish", publish)
    monkeypatch.setattr(host.ntfs, "read", lambda p, limit: p.read_bytes())
    args = (Verifier(), job, files, None, db, scratch, key, None)
    if interruption is None:
        first = host._run_locked(*args)
        assert host._run_locked(*args) == first
        assert first["status"] == "COMPLETE" and first["stdout_sha256"] == hash_bytes(wire)
    else:
        expected = {
            "before_docker_returns": KeyboardInterrupt,
            "before_publish": KeyboardInterrupt,
            "preflight": IsolationUnavailable,
        }.get(interruption, IsolationUncertain)
        with pytest.raises(expected):
            host._run_locked(*args)
        with pytest.raises((IsolationUncertain, FileNotFoundError)):
            host._run_locked(*args)
    assert starts == ([] if interruption == "preflight" else [host.WORKER])


@pytest.mark.skipif(
    os.environ.get("TRADING_LAB_55B_DOCKER") != "1", reason="Explicit Windows Docker acceptance"
)
def test_synthetic_six_cases_in_native_docker(tmp_path):
    registry, scratch = tmp_path / "registry", tmp_path / "scratch"
    registry.mkdir()
    scratch.mkdir()
    result = host.run_synthetic(registry, scratch)
    assert result["audit"]["sample_sizes"] == [7, 7, 4, 4, 3, 3]
    assert result["cleanup"]["exit_code"] == 0
    assert result["preflight"]["probe"][-1] == "ISOLATION_PROBE_OK"


@pytest.mark.skipif(
    os.environ.get("TRADING_LAB_55B_DOCKER") != "1",
    reason="Explicit Windows Docker acceptance",
)
def test_historical_verifier_timeout_and_cleanup_in_native_docker(tmp_path):
    verifier = VerificationContainer()
    with (
        host.ntfs.pinned_root(tmp_path, existing=True),
        host.ntfs.exclusive_lock(tmp_path / ".historical-pilot.lock"),
        host.ntfs.directory(tmp_path / "docker-config", fresh=True, occupy=True),
    ):
        outcome = verifier._execute(
            ["-c", "import time; time.sleep(90)"],
            _payload({}),
            tmp_path,
            "deadline",
            10,
            stdout_capture_limit=MAX_WIRE,
        )
        cleanup = json.loads((tmp_path / "deadline-cleanup.json").read_bytes())
    assert outcome["timed_out"] and cleanup["exit_code"] == 0
