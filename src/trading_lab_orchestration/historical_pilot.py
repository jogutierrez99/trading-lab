"""5.5B host boundary. The existing synthetic entry and old pilot trigger stay unchanged."""

import base64
import os
from datetime import UTC, datetime
from statistics import median
from uuid import uuid4

import pandas as pd

from quant_lab.study_data import COLUMNS

from . import historical_pilot_store as store
from . import study_storage_windows as ntfs
from .contracts import canonical
from .execution_inputs import verified_implementation
from .historical_pilot_contract import (
    CANDLES,
    MANIFEST_SHA,
    WIRE_LIMIT,
    WIRE_MAX,
    Job,
    base64_bound,
    candles_bytes,
    decode_transport,
    frozen_plan,
    hash_bytes,
    parse,
    plan_sha,
    preflight_dataset,
    read_candles,
)
from .historical_pilot_oracle import audit_case
from .isolated_study import LOG_LIMIT, MODULES
from .isolated_study_contract import BASE, IMAGE, PILOT_STRATEGY
from .pilot_authorization import ISSUE_3_TASK, current_operator
from .pilot_launch import read_launch
from .processes import run_process
from .readonly import ReadOnlyStore
from .verification_container import (
    ENDPOINT,
    ROOT,
    RUNTIME,
    IsolationUncertain,
    VerificationContainer,
    _base_sources,
    _payload,
    _regular_bytes,
)

WORKER = ("-m", "trading_lab_orchestration.historical_pilot_guest")
DB = store.DB
BUNDLE_LIMIT = base64_bound(WIRE_MAX) + 3 * LOG_LIMIT
RESULT = "result.json"


class HistoricalVerifier(VerificationContainer):
    """Reuse the pinned verifier and its cleanup with a scoped streaming stdout profile."""

    def __init__(self):
        super().__init__()
        self.streaming_guest = _regular_bytes(RUNTIME, "historical_pilot_bootstrap.py").decode()

    def _cli(self, arguments, folder, name, timeout, payload=None, *, stdout_capture_limit=None):
        if stdout_capture_limit != WIRE_LIMIT:
            return super()._cli(
                arguments, folder, name, timeout, payload, stdout_capture_limit=stdout_capture_limit
            )
        if arguments[0] != "run" or tuple(arguments[-2:]) != WORKER or name != "historical":
            raise ValueError("Extended stdout bound requires the sealed historical worker")
        arguments = arguments.copy()
        arguments[arguments.index(self.guest)] = self.streaming_guest
        config = folder / "docker-config"
        config.mkdir(exist_ok=True)
        return run_process(
            [str(self.docker), "--config", str(config), "--host", ENDPOINT, *arguments],
            folder,
            timeout,
            folder / f"{name}.stdout",
            folder / f"{name}.stderr",
            payload,
            omit_env=tuple(key.upper() for key in os.environ if key.upper().startswith("DOCKER_")),
            output_limit=WIRE_LIMIT,
            stdout_capture_limit=WIRE_LIMIT,
        )


def _fixture(plan):
    first = min(case.start - pd.Timedelta(hours=case.warmup) for case in plan.cases)
    end = max(case.end for case in plan.cases)
    timestamps = pd.date_range(first, end, freq="h", inclusive="left")
    # Piecewise-linear oscillator; enough crosses and various market paths in all six windows.
    rows = []
    for i in range(len(timestamps)):
        cycle = i % 208
        close = 1000 + (cycle if cycle <= 104 else 208 - cycle) + (i % 11) / 8
        width = 1 + (i % 17) / 8
        rows.append((close, close + width, close - width, close, 100 + i % 7))
    return pd.DataFrame(rows, columns=COLUMNS, index=timestamps)


def prepare(verifier, *, data_repo=None):
    if verifier.image != IMAGE:
        raise ValueError("Approved pinned Linux image required")
    plan = frozen_plan(ROOT)
    frame, evidence = (
        (_fixture(plan), None) if data_repo is None else preflight_dataset(data_repo, plan.cases)
    )
    candles = candles_bytes(frame, plan.cases)
    frozen = _base_sources(BASE)
    files = {f"src/quant_lab/{name}.py": frozen[f"src/quant_lab/{name}.py"] for name in MODULES}
    strategy = f"src/quant_lab/strategies/{PILOT_STRATEGY}.py"
    files[strategy] = frozen[strategy]
    # The proposal recorded the Git text with LF; Git for Windows may archive CRLF.
    for path in (strategy, "src/quant_lab/study_backend.py"):
        files[path] = files[path].replace(b"\r\n", b"\n")
        if hash_bytes(files[path]) != plan.input_files[path]:
            raise ValueError(f"Frozen source hash differs from the proposal: {path}")
    package = "src/trading_lab_orchestration"
    for name in (
        "__init__.py",
        "contracts.py",
        "isolated_study_contract.py",
        "historical_pilot_contract.py",
        "historical_pilot_guest.py",
    ):
        files[f"{package}/{name}"] = _regular_bytes(RUNTIME, name)
    files[CANDLES] = candles
    control = {
        name: hash_bytes(_regular_bytes(RUNTIME, name).replace(b"\r\n", b"\n"))
        for name in (
            "historical_pilot.py",
            "historical_pilot_bootstrap.py",
            "historical_pilot_oracle.py",
            "historical_pilot_store.py",
            "readonly.py",
            "study_storage_windows.py",
        )
    }
    job = Job(
        mode="SYNTHETIC" if data_repo is None else "HISTORICAL",
        plan=plan,
        candles_sha256=hash_bytes(candles),
        manifest_sha256=MANIFEST_SHA if data_repo is not None else None,
        supervisor_sha256=hash_bytes(
            canonical(
                {
                    "verifier": verifier.fingerprint,
                    "controls": control,
                    "entrypoint": WORKER,
                }
            ).encode()
        ),
        closure={name: hash_bytes(raw) for name, raw in files.items()},
    )
    files["historical-job.json"] = canonical(job.model_dump(mode="json")).encode()
    return job, files, evidence


def _audit(job, candles, raw):
    frame = read_candles(candles, job)
    summaries = {}
    sizes = []
    distribution = {}
    for case, member in decode_transport(raw, job):
        audit_case(frame, case, job.plan.risk, member)
        summaries[case.id] = member.metrics.model_dump(mode="json")
        sizes.append(len(member.trades))
        pnl = [t.net_pnl for t in member.trades]
        total_abs = sum(abs(value) for value in pnl)
        distribution[case.id] = {
            "median_net_pnl": median(pnl) if pnl else None,
            "worst_net_pnl": min(pnl, default=None),
            "best_net_pnl": max(pnl, default=None),
            "largest_absolute_pnl_share": max(map(abs, pnl)) / total_abs if total_abs else None,
        }
    comparison = {}
    for label in ("train", "validation", "test_retrospective"):
        base, adverse = (summaries[f"{label}_{scenario}"] for scenario in ("base", "adverse"))
        comparison[label] = {
            "net_return_change_pct_points": adverse["return_pct"] - base["return_pct"],
            "closed_trades": [base["closed_trades"], adverse["closed_trades"]],
            "fees_paid": [base["fees_paid"], adverse["fees_paid"]],
        }
    return {
        "metrics": summaries,
        "comparison": comparison,
        "sample_sizes": sizes,
        "trade_distribution": distribution,
        "economic_decision": "NO_DECISION",
    }


def _stamp(root):
    return canonical({"path": str(root).casefold(), "id": ntfs.directory_identity(root)})


def _paths(registry, scratch):
    registry, scratch = ntfs.local_path(registry), ntfs.local_path(scratch)
    a, b = ntfs.directory_identity(registry), ntfs.directory_identity(scratch)
    if (
        a == b
        or any(ntfs.directory_identity(p) == a for p in scratch.parents)
        or any(ntfs.directory_identity(p) == b for p in registry.parents)
    ):
        raise ValueError("Historical registry and scratch must be independent dedicated roots")


def _read_complete(folder, seal, job, candles):
    raw = ntfs.read(folder / RESULT, BUNDLE_LIMIT)
    if hash_bytes(raw) != seal:
        raise ValueError("Historical evidence does not match the consumed permit seal")
    result = parse(raw)
    transport = base64.b64decode(result["stdout"], validate=True)
    if (
        result["status"] != "COMPLETE"
        or result["job_sha256"] != plan_sha(job)
        or result["stdout_sha256"] != hash_bytes(transport)
        or result["audit"] != _audit(job, candles, transport)
    ):
        raise ValueError("Historical receipt integrity mismatch")
    return result


def _run(verifier, job, files, evidence, registry, scratch, permit_id, binding=None):
    with (
        ntfs.pinned_root(registry, existing=True) as trusted,
        ntfs.pinned_root(scratch, existing=True) as root,
    ):
        _paths(trusted, root)
        registry_lock = (
            trusted.parent / store.LOCK
            if job.mode == "HISTORICAL"
            else trusted / ".historical-pilot.lock"
        )
        with (
            ntfs.exclusive_lock(registry_lock),
            ntfs.exclusive_lock(root / ".historical-pilot.lock"),
        ):
            return _run_locked(
                verifier, job, files, evidence, trusted / DB, root, permit_id, binding
            )


def _run_locked(verifier, job, files, evidence, database, root, permit_id, binding):
    folder = root / job.plan.job_id
    purpose = "HISTORICAL_BACKTEST_ONCE" if job.mode == "HISTORICAL" else "SYNTHETIC_BACKTEST_ONCE"
    fresh, (folder_id, state, seal) = store.reserve(
        database,
        permit_id,
        plan_sha(job),
        purpose,
        _stamp(root),
        binding,
    )
    if not fresh:
        if state != "SEALED":
            raise IsolationUncertain("Historical reservation requires operator reconciliation")
        try:
            with ntfs.directory(folder):
                if _stamp(folder) != folder_id:
                    raise IsolationUncertain("Historical evidence directory identity changed")
                return _read_complete(folder, seal, job, files[CANDLES])
        except FileNotFoundError as exc:
            raise IsolationUncertain(
                "Historical seal without result requires reconciliation"
            ) from exc

    with ntfs.directory(folder, fresh=True, occupy=True):
        store.bind_job(database, permit_id, _stamp(folder))
        try:
            result = _execute(verifier, job, files, evidence, folder)
        except (ValueError, OSError, IsolationUncertain) as exc:
            store.finish(database, permit_id)
            ntfs.publish(
                folder / "failure.json",
                canonical(
                    {
                        "status": "UNKNOWN",
                        "job_sha256": plan_sha(job),
                        "error": str(exc),
                        "utc": datetime.now(UTC).isoformat(),
                    }
                ).encode(),
                LOG_LIMIT,
            )
            raise
        packed = canonical(result).encode()
        if len(packed) >= BUNDLE_LIMIT:
            raise IsolationUncertain("Historical receipt exceeds storage bound")
        store.finish(database, permit_id, bundle_sha=hash_bytes(packed))
        ntfs.publish(folder / RESULT, packed, BUNDLE_LIMIT)
        return result


def _execute(verifier, job, files, evidence, folder):
    diagnostics = folder / "preflight"
    with (
        ntfs.directory(diagnostics, fresh=True, occupy=True),
        ntfs.directory(diagnostics / "docker-config", fresh=True, occupy=True),
    ):
        probe = verifier.preflight(
            diagnostics=diagnostics, read_bytes=lambda p: ntfs.read(p, LOG_LIMIT)
        )
    with ntfs.directory(folder / "docker-config", fresh=True, occupy=True):
        outcome = verifier._execute(
            WORKER,
            _payload(files),
            folder,
            "historical",
            job.plan.limits.wall_seconds,
            stdout_capture_limit=WIRE_LIMIT,
        )
    cleanup = parse(ntfs.read(folder / "historical-cleanup.json", LOG_LIMIT))
    raw = outcome.get("stdout_bytes")
    if not verifier._ok(outcome) or not verifier._ok(cleanup) or not isinstance(raw, bytes):
        raise IsolationUncertain("Historical run or cleanup is not verified")
    return {
        "schema_version": "1.0",
        "status": "COMPLETE",
        "job_sha256": plan_sha(job),
        "job": job.model_dump(mode="json"),
        "dataset_preflight": evidence,
        "preflight": probe,
        "cleanup": cleanup,
        "process": {k: outcome[k] for k in ("exit_code", "timed_out", "duration_seconds")},
        "stdout": base64.b64encode(raw).decode("ascii"),
        "stdout_sha256": hash_bytes(raw),
        "audit": _audit(job, files[CANDLES], raw),
    }


class _HistoricalCoordinator(ReadOnlyStore):
    def _open_reader(self):
        return store.rollback_snapshot(self.path)


def _verified_binding(coordinator_db):
    database = _HistoricalCoordinator(coordinator_db)
    with database.snapshot():
        with database.connection() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='trigger' "
                    "AND name='pilot_launch_no_backtest'"
                ).fetchone()
                is None
            ):
                raise ValueError("Original pilot backtest guard is not present")
            rows = connection.execute(
                """SELECT l.authorization_id,a.attempt_id FROM attempts a
                   JOIN pilot_launch_authorizations l ON l.attempt_id=a.attempt_id
                   WHERE a.task_id=? AND a.status='SUCCEEDED' AND l.state='CONSUMED'""",
                (ISSUE_3_TASK,),
            ).fetchall()
            if len(rows) != 1:
                raise ValueError("Expected one verified Issue #3 implementation")
            row, attempt = rows[0]
            _, launch = read_launch(connection, row)
            if (launch.task_id, launch.attempt_id) != (ISSUE_3_TASK, attempt):
                raise ValueError("Sealed launch identity differs from Issue #3")
            operator = current_operator()
            if operator[1] != launch.operator_sid:
                raise ValueError("Historical operator differs from the sealed launch operator")
        _, _, receipt_path, receipt = verified_implementation(database, attempt)
    plan = frozen_plan(ROOT)
    for name in (
        f"src/quant_lab/strategies/{PILOT_STRATEGY}.py",
        f"configs/strategies/{PILOT_STRATEGY}.yaml",
    ):
        if not (
            receipt["files"].get(name)
            == plan.input_files[name]
            == hash_bytes((ROOT / name).read_bytes().replace(b"\r\n", b"\n"))
        ):
            raise ValueError("Approved implementation differs from the frozen published files")
    return attempt, hash_bytes(receipt_path.read_bytes()), *operator


def authorization_proposal(data_repo, coordinator_db, registry):
    job, _, evidence = prepare(HistoricalVerifier(), data_repo=data_repo)
    attempt, receipt, operator, sid = _verified_binding(coordinator_db)
    store.assert_unconsumed(registry / DB, store.ISSUE_SCOPE, operator=(operator, sid))
    permit = store.Permit(
        purpose="HISTORICAL_BACKTEST_ONCE",
        attempt_id=attempt,
        implementation_receipt_sha256=receipt,
        job_sha256=plan_sha(job),
        operator=operator,
        operator_sid=sid,
        approved_at=datetime.now(UTC),
    )
    return permit, job, evidence


def approve_historical(data_repo, coordinator_db, registry, *, expected_job_sha256):
    """Future operator action, independent of preparation and without running Docker."""
    permit, job, _ = authorization_proposal(data_repo, coordinator_db, registry)
    if permit.job_sha256 != expected_job_sha256:
        raise ValueError("Historical job SHA-256 changed before approval")
    print(canonical(job.model_dump(mode="json")))
    return store.grant(registry / DB, permit)


def run_historical(data_repo, coordinator_db, registry, scratch, permit_id):
    """Operator-only entry. A prepared proposal never grants or consumes a permit by itself."""
    verifier = HistoricalVerifier()
    job, files, evidence = prepare(verifier, data_repo=data_repo)
    binding = _verified_binding(coordinator_db)
    with (
        store.operator_registry(registry / DB, binding[2:]) as root,
        ntfs.pinned_root(scratch, existing=True) as output,
        store.guard_registry_file(root, binding[3]),
    ):
        store.check_acl(output, binding[3], private=True)
        for protected in (ROOT, data_repo.resolve(), coordinator_db.resolve().parent):
            if output.is_relative_to(protected) or protected.is_relative_to(output):
                raise ValueError(
                    "Historical scratch must be outside code, data and coordinator roots"
                )
        return _run(verifier, job, files, evidence, root, output, permit_id, binding)


def run_synthetic(registry, scratch):
    """Acceptance only. Generates its own candles and synthetic permit in a fresh registry."""
    protected = store.designated_registry()
    for path in (ntfs.local_path(registry), ntfs.local_path(scratch)):
        if path.is_relative_to(protected) or protected.is_relative_to(path):
            raise ValueError("Synthetic runs require storage separate from the historical registry")
    verifier = HistoricalVerifier()
    job, files, _ = prepare(verifier)
    permit = store.Permit(
        purpose="SYNTHETIC_BACKTEST_ONCE",
        attempt_id="attempt_" + uuid4().hex,
        implementation_receipt_sha256="0" * 64,
        job_sha256=plan_sha(job),
        operator="synthetic-acceptance",
        operator_sid="S-1-0-0",
        approved_at=datetime.now(UTC),
    )
    with (
        ntfs.pinned_root(registry, existing=True) as root,
        ntfs.exclusive_lock(root / ".historical-pilot.lock"),
    ):
        database = root / DB
        if database.exists():
            key = store.synthetic_key(database, permit.scope)
        else:
            store.initialize(database)
            key = store.grant(database, permit, store.phrase(permit))
    result = _run(verifier, job, files, None, registry, scratch, key)
    if _run(verifier, job, files, None, registry, scratch, key) != result:
        raise ValueError("Historical acceptance replay diverged")
    return result
