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
    BLOCK_BYTES,
    CANDLES,
    EVENT_BYTES,
    WIRE_LIMIT,
    WIRE_MAX,
    BlockedDataset,
    Job,
    candles_bytes,
    case_bound,
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
    assert len(wire) <= WIRE_MAX
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
    assert 80 * 1024 < len(wire) <= WIRE_MAX
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
        "above",
        "truncated",
        "duplicate_key",
        "missing",
        "duplicate",
        "order",
        "hash",
        "case_hash",
        "extra",
        "overflow",
        "wrong_job",
        "nonfinite",
        "oversized_frame",
    ],
)
def test_transport_rejects_malformed_or_unsealed_parts(synthetic, attack):
    job, _, _, _, wire = synthetic
    lines = wire.splitlines(keepends=True)
    block = json.loads(lines[2])
    if attack == "above":
        wire += b" " * (WIRE_LIMIT - len(wire))
    elif attack == "truncated":
        wire = wire[:-3]
    elif attack == "duplicate_key":
        wire = wire.replace(b'{"job_sha256"', b'{"schema_version":"2.0","job_sha256"', 1)
    elif attack == "missing":
        lines.pop(2)
        wire = b"".join(lines)
    elif attack == "duplicate":
        lines.insert(2, lines[2])
        wire = b"".join(lines)
    elif attack == "order":
        lines[1], lines[2] = lines[2], lines[1]
        wire = b"".join(lines)
    elif attack == "case_hash":
        part = json.loads(lines[1])
        part["sha256"] = "0" * 64
        wire = lines[0] + canonical(part).encode() + b"\n" + b"".join(lines[2:])
    elif attack == "wrong_job":
        wire = wire.replace(plan_sha(job).encode(), b"0" * 64, 1)
    elif attack == "nonfinite":
        wire = (
            b"".join(lines[:1])
            + lines[1].replace(b'"bytes":', b'"bytes":NaN,"unused":', 1)
            + b"".join(lines[2:])
        )
    elif attack == "oversized_frame":
        wire = b" " * 300 + wire
    else:
        if attack == "hash":
            block["sha256"] = "0" * 64
        elif attack == "extra":
            block["extra"] = True
        else:
            block["codec"] = "zlib"
            block["data"] = base64.b64encode(zlib.compress(b"x" * (BLOCK_BYTES + 1))).decode()
        wire = b"".join(lines[:2]) + canonical(block).encode() + b"\n" + b"".join(lines[3:])
    with pytest.raises(ValueError):
        list(decode_transport(wire, job))


def test_streaming_profile_is_used_only_for_the_frozen_worker(tmp_path, monkeypatch):
    verifier = object.__new__(host.HistoricalVerifier)
    verifier.image = IMAGE
    verifier.docker = tmp_path / "docker.exe"
    verifier.fingerprint = "0" * 64
    verifier.guest = "legacy guest"
    verifier.streaming_guest = "streaming guest"
    calls = []

    def process(argv, cwd, timeout, stdout, stderr, payload, **limits):
        calls.append((argv, limits))
        status = {"exit_code": 0, "timed_out": False, "output_truncated": False}
        return status | ({"stdout_bytes": b"framed"} if "run" in argv else {})

    monkeypatch.setattr(host, "run_process", process)
    monkeypatch.setattr(
        host.VerificationContainer,
        "_cli",
        lambda *args, **kwargs: process(
            args[1],
            None,
            None,
            None,
            None,
            None,
            **kwargs,
        ),
    )
    assert (
        verifier._execute(
            host.WORKER,
            "payload",
            tmp_path,
            "historical",
            60,
            stdout_capture_limit=WIRE_LIMIT,
        )["stdout_bytes"]
        == b"framed"
    )
    first, last = calls
    assert "streaming guest" in first[0] and "legacy guest" not in first[0]
    assert not any(flag in first[0] for flag in ("--mount", "--privileged"))
    assert first[1]["stdout_capture_limit"] == WIRE_LIMIT
    assert last[0][0] == "rm" and last[1]["stdout_capture_limit"] is None
    with pytest.raises(ValueError, match="sealed historical worker"):
        verifier._cli(
            ["run", "anything"], tmp_path, "historical", 5, stdout_capture_limit=WIRE_LIMIT
        )


def test_all_case_event_slots_fit_even_without_compression(synthetic, monkeypatch):
    job, _, _, cases, _ = synthetic
    stressed = deepcopy(cases)
    worst_float = float.fromhex("0x1.fffffffffffffp+1023")
    assert len(canonical(-worst_float)) == 24
    for case, value in zip(job.plan.cases, stressed, strict=True):
        trade = value["trades"][0]
        for key, field in trade.items():
            if type(field) is float:
                trade[key] = -worst_float if key == "net_pnl" else worst_float
        trade.update(holding_bars=case.bars, reason="end_of_study", exit_timing="intrabar")
        assert len(canonical(trade).encode()) < EVENT_BYTES
        value["trades"] = [trade] * (case.bars - 1)
        value["rejections"] = []
        value["equity"] = [worst_float] * (case.bars + 1)
        value["exposure"] = [worst_float] * (case.bars + 1)
        assert len(canonical(value).encode()) <= case_bound(case.bars)
    # Model all blocks taking the raw path. There is no favorable compression assumption.
    monkeypatch.setattr(zlib, "compress", lambda data, **kwargs: data + b"!")
    wire = encode_transport(job, stressed)
    results = list(decode_transport(wire, job))
    assert 512 * 1024 < len(wire) <= WIRE_MAX
    assert sum(len(result.trades) for _, result in results) == 5754
    with pytest.raises(SemanticInconsistency):
        host._audit(job, synthetic[1][CANDLES], wire)


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
    with pytest.raises(ValueError, match="Windows operator"):
        store.reserve(database, key, permit.job_sha256, "HISTORICAL_BACKTEST_ONCE", "dir")
    assert store.reserve(database, key, permit.job_sha256, permit.purpose, "dir")[0]


def test_historical_direct_grant_and_reserve_reject_prefilled_consent(permit_db):
    database, original = permit_db
    permit = store.Permit.model_validate_json(
        original.model_copy(
            update={"purpose": "HISTORICAL_BACKTEST_ONCE"},
        ).model_dump_json()
    )
    with pytest.raises(ValueError, match="interactively"):
        store.grant(database, permit, store.phrase(permit))
    with pytest.raises(ValueError, match="Windows operator"):
        store.reserve(database, store.receipt_id(permit), permit.job_sha256, permit.purpose, "dir")
    with store.transaction(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM permits").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_proposal_registry_check_is_read_only(permit_db):
    database, permit = permit_db
    before = database.read_bytes()
    store.assert_unconsumed(database, permit.scope)
    assert database.read_bytes() == before
    key = store.grant(database, permit, store.phrase(permit))
    store.reserve(database, key, permit.job_sha256, permit.purpose, "dir")
    consumed = database.read_bytes()
    with pytest.raises(ValueError, match="already consumed"):
        store.assert_unconsumed(database, permit.scope)
    assert database.read_bytes() == consumed


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
    [
        None,
        "before_docker_returns",
        "before_publish",
        "preflight",
        "timeout",
        "cleanup",
        "capture",
        "missing_block",
    ],
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
            assert stdout_capture_limit == WIRE_LIMIT
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
                "stdout_bytes": None
                if interruption == "capture"
                else (
                    b"".join(wire.splitlines(keepends=True)[:-1])
                    if interruption == "missing_block"
                    else wire
                ),
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
            "missing_block": ValueError,
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
    verifier = host.HistoricalVerifier()
    with (
        host.ntfs.pinned_root(tmp_path, existing=True),
        host.ntfs.exclusive_lock(tmp_path / ".historical-pilot.lock"),
        host.ntfs.directory(tmp_path / "docker-config", fresh=True, occupy=True),
    ):
        outcome = verifier._execute(
            host.WORKER,
            _payload(
                {
                    "src/trading_lab_orchestration/__init__.py": b"",
                    "src/" + host.WORKER[-1].replace(".", "/") + ".py": (
                        b"import time; time.sleep(90)"
                    ),
                }
            ),
            tmp_path,
            "historical",
            10,
            stdout_capture_limit=WIRE_LIMIT,
        )
        cleanup = json.loads((tmp_path / "historical-cleanup.json").read_bytes())
    assert outcome["timed_out"] and cleanup["exit_code"] == 0
