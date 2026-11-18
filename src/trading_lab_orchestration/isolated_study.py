"""5.5A host adapter. Its only callable execution path builds its own synthetic inputs."""

import base64
import binascii
import hashlib
import json
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

from pydantic import TypeAdapter

from . import study_storage_windows as storage
from .contracts import canonical, digest
from .isolated_study_contract import (
    BASE,
    DATA,
    DEPENDENCIES,
    IMAGE,
    MAX_WIRE,
    Case,
    Costs,
    Key,
    Limits,
    Plan,
    Reception,
    Risk,
    decode_result,
    synthetic_fixture,
)
from .verification_container import (
    RUNTIME,
    IsolationUncertain,
    VerificationContainer,
    _base_sources,
    _payload,
    _regular_bytes,
)
from .workspaces import file_hash

MODULES = (
    "__init__",
    "backtest",
    "binance_history",
    "candles",
    "config",
    "execution_config",
    "features",
    "history",
    "metrics",
    "risk",
    "strategies/__init__",
    "strategies/base",
    "study_backend",
    "study_data",
)
ENTRYPOINT = ("-m", "trading_lab_orchestration.isolated_study_guest")
LOG_FILES = (
    "study-container.json",
    "study.stderr",
    "study-cleanup.json",
    "study-cleanup.stdout",
    "study-cleanup.stderr",
)


def synthetic_job(job_id, fingerprint, *, timeout=60):
    """Build exact input bytes from D and a fixed fixture. No dataset or command parameters."""
    stored = _base_sources(BASE)
    files = {f"src/quant_lab/{name}.py": stored[f"src/quant_lab/{name}.py"] for name in MODULES}
    for name in (
        "__init__.py",
        "contracts.py",
        "isolated_study_contract.py",
        "isolated_study_guest.py",
    ):
        files[f"src/trading_lab_orchestration/{name}"] = _regular_bytes(RUNTIME, name)
    files[DATA] = synthetic_fixture()
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    risk = Risk(
        initial_cash=10000.0,
        risk_per_trade_pct=0.5,
        max_position_pct=100.0,
        max_exposure_pct=100.0,
        atr_period=14,
        atr_multiplier=2.0,
        risk_reward=2.0,
        quantity_step=0.000001,
        min_quantity=0.000001,
        min_notional=10.0,
    )
    start = datetime(2000, 1, 1, 16, tzinfo=UTC)
    cases = [
        Case(
            id=f"synthetic_{name}",
            segment="synthetic",
            scenario=name,
            start=start,
            end=start + timedelta(hours=20),
            warmup=16,
            costs=Costs(
                trading_fee_pct=0.10 * multiplier,
                slippage_pct=0.03 * multiplier,
                spread_pct=0.02 * multiplier,
            ),
        )
        for name, multiplier in (("base", 1), ("adverse", 2))
    ]
    plan = Plan(
        kind="SYNTHETIC_ACCEPTANCE",
        job_id=job_id,
        strategy="fixed_synthetic_signals",
        code_commit=BASE,
        engine_sha256=hashes["src/quant_lab/study_backend.py"],
        protocol_sha256=digest(
            canonical(
                {
                    "container": fingerprint,
                    "host": file_hash(Path(__file__)),
                    "storage": file_hash(Path(storage.__file__)),
                    "entrypoint": ENTRYPOINT,
                }
            )
        ),
        dependencies_sha256=digest(canonical(DEPENDENCIES)),
        image=IMAGE,
        input_files=hashes,
        dataset_id=digest("study-backend-5-5a-synthetic-v1"),
        dataset_sha256=hashes[DATA],
        parameters={},
        risk=risk,
        limits=Limits(max_cases=2, wall_seconds=timeout),
        cases=cases,
    )
    files["plan.json"] = canonical(plan.model_dump(mode="json")).encode()
    return plan, files


LOG_LIMIT = 1024 * 1024
BUNDLE_LIMIT = 10 * 1024 * 1024
PREFLIGHT = "isolation-preflight.json"
CLEANUP = "study-cleanup.json"
TERMINAL = "result.json"
FINAL = {"COMPLETE", "FAILED", "TIMED_OUT"}
_bounded_bytes = storage.read


def _pack(record, capture, logs):
    body = {
        "receipt": record,
        "stdout": base64.b64encode(capture).decode("ascii") if capture is not None else None,
        "logs": {name: base64.b64encode(raw).decode("ascii") for name, raw in logs.items()},
    }
    return canonical({"body": body, "body_sha256": digest(canonical(body))}).encode()


def _unpack(path):
    raw = _bounded_bytes(path, BUNDLE_LIMIT)
    bundle = json.loads(raw)
    if (
        not isinstance(bundle, dict)
        or bundle.keys() != {"body", "body_sha256"}
        or bundle["body_sha256"] != digest(canonical(bundle["body"]))
        or raw != canonical(bundle).encode()
    ):
        raise ValueError("Stored study bundle integrity check failed")
    body = bundle["body"]
    if not isinstance(body, dict) or body.keys() != {"receipt", "stdout", "logs"}:
        raise ValueError("Invalid study bundle")
    record = body["receipt"]
    Reception.model_validate_json(canonical(record))
    logs = body["logs"]
    if not isinstance(logs, dict) or logs.keys() != record["evidence_sha256"].keys():
        raise ValueError("Stored execution evidence does not match the receipt")
    for name, encoded in logs.items():
        if name not in (*LOG_FILES, PREFLIGHT):
            raise ValueError("Unexpected execution evidence")
        data = _unbase64(encoded, LOG_LIMIT)
        if hashlib.sha256(data).hexdigest() != record["evidence_sha256"][name]:
            raise ValueError("Stored execution evidence changed")
    if record["status"] == "COMPLETE":
        if not {CLEANUP, PREFLIGHT} <= logs.keys():
            raise ValueError("Completed result lacks execution or cleanup evidence")
        capture = _unbase64(body["stdout"], MAX_WIRE)
        if hashlib.sha256(capture).hexdigest() != record["output_sha256"]:
            raise ValueError("Accepted evidence SHA-256 changed")
        if json.loads(capture) != record["export"]:
            raise ValueError("Stored export changed")
        return record, capture
    elif body["stdout"] is not None:
        raise ValueError("A partial result cannot contain accepted stdout")
    return record, None


def _unbase64(encoded, limit):
    if not isinstance(encoded, str) or len(encoded) > 4 * ((limit + 2) // 3):
        raise ValueError("Invalid stored capture size or type")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except binascii.Error as exc:
        raise ValueError("Invalid stored capture encoding") from exc
    if len(decoded) >= limit or base64.b64encode(decoded).decode("ascii") != encoded:
        raise ValueError("Invalid stored capture size or encoding")
    return decoded


def _read_terminal(path, plan, plan_sha):
    record, capture = _unpack(path)
    if (
        record["job_id"] != plan.job_id
        or record["plan_sha256"] != plan_sha
        or record["environment"]
        != {
            "image": plan.image,
            "engine_sha256": plan.engine_sha256,
            "protocol_sha256": plan.protocol_sha256,
        }
    ):
        raise ValueError("Job identity already bound to a different plan")
    if record["status"] == "COMPLETE":
        decode_result(capture, plan)
    return record


def _reserved_plan(job):
    raw = _bounded_bytes(job / "reservation.json", LOG_LIMIT)
    reservation = json.loads(raw)
    if (
        not isinstance(reservation, dict)
        or reservation.keys() != {"schema_version", "state", "plan_sha256", "plan"}
        or reservation["schema_version"] != "1.0"
        or reservation["state"] != "RESERVED"
        or raw != canonical(reservation).encode()
        or reservation["plan_sha256"] != digest(canonical(reservation["plan"]))
    ):
        raise ValueError("Invalid study reservation")
    return reservation["plan_sha256"]


def run_synthetic(job_id, scratch: Path, *, timeout=60):
    """One execution on a dedicated Windows NTFS root. Historical input cannot enter here."""
    TypeAdapter(Key).validate_python(job_id, strict=True)
    if storage.reserved_name(job_id):
        raise ValueError("Reserved study job name")
    verifier = VerificationContainer()
    if verifier.image != IMAGE:
        raise ValueError("Approved verifier image required")
    plan, files = synthetic_job(job_id, verifier.fingerprint, timeout=timeout)
    plan_sha = digest(files["plan.json"].decode())
    with (
        storage.pinned_root(scratch) as root,
        storage.exclusive_lock(root / ".isolated-study.lock"),
    ):
        job = root / job_id
        # The directory is itself a reservation marker. A crash before recording the plan
        # or publishing the bundle leaves it unresolved, including a crash during rename.
        if job.exists() or job.is_symlink() or job.is_junction():
            with storage.directory(job):
                try:
                    if _reserved_plan(job) != plan_sha:
                        raise ValueError("Job identity already bound to a different plan")
                    return _read_terminal(job / TERMINAL, plan, plan_sha)
                except FileNotFoundError as exc:
                    raise IsolationUncertain(
                        "An interrupted reservation requires reconciliation"
                    ) from exc

        for previous in root.iterdir():
            if previous.name == ".isolated-study.lock":
                continue
            with storage.directory(previous):
                try:
                    prior, _ = _unpack(previous / TERMINAL)
                    prior_plan = _reserved_plan(previous)
                except FileNotFoundError as exc:
                    raise IsolationUncertain(
                        "An interrupted reservation requires reconciliation"
                    ) from exc
                if (
                    prior["job_id"] != previous.name
                    or prior["plan_sha256"] != prior_plan
                    or prior["status"] not in FINAL
                ):
                    raise IsolationUncertain("An uncertain study requires reconciliation")
        with storage.directory(job, fresh=True, occupy=True):
            return _reserve_and_run(job, verifier, plan, files, plan_sha)


def _reserve_and_run(job, verifier, plan, files, plan_sha):
    storage.publish(
        job / "reservation.json",
        canonical(
            {
                "schema_version": "1.0",
                "state": "RESERVED",
                "plan_sha256": plan_sha,
                "plan": plan.model_dump(mode="json"),
            }
        ).encode(),
        LOG_LIMIT,
    )
    with storage.directory(job / "docker-config", create=True, occupy=True):
        return _run_reserved(verifier, job, plan, files, plan_sha)


def _run_reserved(verifier, job, plan, files, plan_sha):
    record = {
        "schema_version": "1.2",
        "plan_sha256": plan_sha,
        "job_id": plan.job_id,
        "environment": {
            "image": plan.image,
            "engine_sha256": plan.engine_sha256,
            "protocol_sha256": plan.protocol_sha256,
        },
        "started_at_utc": datetime.now(UTC).isoformat(),
    }
    interrupted = None
    capture = None
    logs = {}
    try:
        diagnostics = job / "preflight"
        with (
            storage.directory(diagnostics, fresh=True, occupy=True),
            storage.directory(diagnostics / "docker-config", fresh=True, occupy=True),
        ):
            preflight = verifier.preflight(
                diagnostics=diagnostics, read_bytes=partial(_bounded_bytes, limit=LOG_LIMIT)
            )
        logs[PREFLIGHT] = canonical(preflight).encode()
        if len(logs[PREFLIGHT]) >= LOG_LIMIT:
            logs.pop(PREFLIGHT)
            raise ValueError("Preflight evidence exceeds limit")
        outcome = verifier._execute(
            ENTRYPOINT, _payload(files), job, "study", plan.limits.wall_seconds
        )
        record["process"] = {k: outcome[k] for k in ("exit_code", "timed_out", "duration_seconds")}
        logs[CLEANUP] = _bounded_bytes(job / CLEANUP, LOG_LIMIT)
        cleanup = json.loads(logs[CLEANUP])
        if not verifier._ok(cleanup):
            raise IsolationUncertain("Study container cleanup not confirmed")
        record["cleanup_confirmed"] = True
        for name in LOG_FILES:
            if name != CLEANUP:
                try:
                    logs[name] = _bounded_bytes(job / name, LOG_LIMIT)
                except FileNotFoundError:
                    pass
        if outcome["timed_out"]:
            record["status"] = "TIMED_OUT"
        elif not verifier._ok(outcome):
            raise ValueError("Study subprocess failed or output exceeded its limit")
        else:
            raw = _bounded_bytes(job / "study.stdout", plan.limits.output_bytes)
            decode_result(raw, plan)
            capture = raw
    except ValueError as exc:
        record.update(status="FAILED", reason=str(exc))
    except (OSError, IsolationUncertain, KeyboardInterrupt) as exc:
        record.update(status="UNKNOWN", reason=str(exc) or type(exc).__name__)
        if isinstance(exc, KeyboardInterrupt):
            interrupted = exc
    record["ended_at_utc"] = datetime.now(UTC).isoformat()
    record["evidence_sha256"] = {
        name: hashlib.sha256(data).hexdigest() for name, data in logs.items()
    }
    if capture is not None:
        record.update(
            status="COMPLETE",
            export=json.loads(capture),
            output_sha256=hashlib.sha256(capture).hexdigest(),
        )
    Reception.model_validate_json(canonical(record))
    try:
        storage.publish(job / TERMINAL, _pack(record, capture, logs), BUNDLE_LIMIT)
    except (OSError, ValueError) as exc:
        raise IsolationUncertain(
            "Could not publish the bundle; inspect the reserved study"
        ) from exc
    if interrupted:
        raise interrupted
    return record
