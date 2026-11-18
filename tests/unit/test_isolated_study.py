import base64
import ctypes
import hashlib
import json
import os
import struct
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from ctypes import wintypes
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from trading_lab_orchestration import isolated_study as study
from trading_lab_orchestration.contracts import canonical, digest
from trading_lab_orchestration.isolated_study_contract import (
    IMAGE,
    MAX_WIRE,
    Plan,
    Result,
    SemanticInconsistency,
    decode_result,
    synthetic_fixture,
)
from trading_lab_orchestration.verification_container import (
    IsolationUnavailable,
    IsolationUncertain,
    VerificationContainer,
    _payload,
)
from trading_lab_orchestration.workspaces import write_json

pytestmark = pytest.mark.filterwarnings("error")


def flat_export(plan):
    files = {
        f"cases/{case.id}.json": {
            "id": case.id,
            "scenario": case.scenario,
            "segment": case.segment,
            "costs": case.costs.model_dump(mode="json"),
            "trades": [],
            "rejections": [],
            "open_position": None,
            "equity": [plan.risk.initial_cash] * (case.bars + 1),
            "exposure": [0.0] * (case.bars + 1),
            "metrics": {
                "closed_trades": 0,
                "return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "expectancy": None,
                "profit_factor": None,
                "win_rate_pct": None,
                "average_close_exposure_pct": 0.0,
                "fees_paid": 0.0,
                "realized_net_pnl": 0.0,
                "slippage_cost_closed_trades": 0.0,
                "spread_cost_closed_trades": 0.0,
                "rejected_entries": 0,
            },
        }
        for case in plan.cases
    }
    return {
        "schema_version": "1.1",
        "status": "COMPLETE",
        "job_id": plan.job_id,
        "plan_sha256": digest(canonical(plan.model_dump(mode="json"))),
        "image": plan.image,
        "engine_sha256": plan.engine_sha256,
        "dataset_sha256": plan.dataset_sha256,
        "dependencies_sha256": plan.dependencies_sha256,
        "files": files,
        "sha256": {name: digest(canonical(value)) for name, value in files.items()},
    }


@pytest.fixture
def plan():
    return study.synthetic_job("test_study", "a" * 64)[0]


BASE_CASE = "cases/synthetic_base.json"


def reseal(export):
    export["sha256"] = {key: digest(canonical(case)) for key, case in export["files"].items()}
    raw = canonical(export).encode()
    Result.model_validate_json(raw)
    return raw


def refresh_metrics(case):
    equity = case["equity"]
    pnl = [t["net_pnl"] for t in case["trades"]]
    profits = sum(v for v in pnl if v > 0)
    losses = -sum(v for v in pnl if v < 0)
    case["metrics"].update(
        closed_trades=len(pnl),
        return_pct=100 * (equity[-1] / equity[0] - 1),
        max_drawdown_pct=100
        * max(1 - value / max(equity[: i + 1]) for i, value in enumerate(equity)),
        expectancy=sum(pnl) / len(pnl) if pnl else None,
        profit_factor=profits / losses if losses else None,
        win_rate_pct=100 * sum(v > 0 for v in pnl) / len(pnl) if pnl else None,
        average_close_exposure_pct=100 * sum(case["exposure"][1:]) / (len(equity) - 1),
        fees_paid=sum(t["entry_fee"] + t["exit_fee"] for t in case["trades"]),
        realized_net_pnl=sum(pnl),
        slippage_cost_closed_trades=sum(t["slippage_cost"] for t in case["trades"]),
        spread_cost_closed_trades=sum(t["spread_cost"] for t in case["trades"]),
    )


def corrupt_flat(export):
    case = export["files"][BASE_CASE]
    case["equity"][1] *= 0.5
    case["exposure"][1] = 0.5
    refresh_metrics(case)
    return reseal(export)


@pytest.fixture
def valid_export(plan):
    fixture = Path(__file__).resolve().parents[1] / "fixtures/isolated_study_synthetic_cases.json"
    exported = flat_export(plan)
    exported["files"] = json.loads(fixture.read_bytes())
    decode_result(reseal(exported), plan)
    return exported


@pytest.fixture
def simulated(monkeypatch):
    if os.name != "nt":
        pytest.skip("Synthetic host study persistence requires Windows NTFS")

    class Verifier:
        image = IMAGE
        fingerprint = "a" * 64
        outcome = "ok"
        starts = 0
        wait = None
        started = Event()

        def preflight(self, *, diagnostics, read_bytes):
            assert diagnostics.name == "preflight"
            assert (diagnostics / "docker-config").is_dir()
            return {"probe": ["ISOLATION_PROBE_OK"]}

        def _execute(self, command, payload, folder, name, timeout):
            assert command == study.ENTRYPOINT
            self.starts += 1
            self.started.set()
            if self.wait is not None:
                assert self.wait.wait(timeout=10)
            if self.outcome == "interrupt":
                raise KeyboardInterrupt
            if self.outcome == "uncertain":
                raise IsolationUncertain("cleanup not confirmed")
            plan, _ = study.synthetic_job(folder.name, self.fingerprint, timeout=timeout)
            output = canonical(flat_export(plan)) if self.outcome != "invalid" else "garbage"
            if self.outcome == "manipulated":
                output = corrupt_flat(flat_export(plan)).decode()
            (folder / f"{name}.stdout").write_text(output, encoding="utf-8")
            write_json(
                folder / f"{name}-cleanup.json",
                {"exit_code": 0, "timed_out": False, "output_truncated": False},
            )
            return {
                "exit_code": 0,
                "timed_out": self.outcome == "timeout",
                "duration_seconds": 0.01,
                "output_truncated": False,
            }

        @staticmethod
        def _ok(result):
            return not (result["timed_out"] or result["exit_code"] or result["output_truncated"])

    verifier = Verifier()
    monkeypatch.setattr(study, "VerificationContainer", lambda: verifier)
    return verifier


def _bundle(path):
    return json.loads((path / study.TERMINAL).read_bytes())["body"]


def test_preflight_uses_fixed_paths_and_does_not_delete_diagnostics(tmp_path, monkeypatch):
    # Exercise the shared preflight with a supervised path and simulated Docker calls.
    root = tmp_path / "preflight"
    root.mkdir()
    sentinel = tmp_path / "outside.txt"
    sentinel.write_bytes(b"outside")
    protected = set()
    verifier = object.__new__(VerificationContainer)
    verifier.image = IMAGE
    verifier.fingerprint = "a" * 64

    def refuse_legacy_temp(*args, **kwargs):
        raise AssertionError("This mode must not allocate a system temporary folder")

    def inspect(arguments, folder, name, timeout):
        assert folder == root and name == "image"
        (folder / "image.stdout").write_text(
            json.dumps([{"Id": IMAGE, "Os": "linux", "Config": {}}]), encoding="utf-8"
        )
        return {
            "exit_code": 0,
            "timed_out": False,
            "output_truncated": False,
            "stdout": str(sentinel),
        }

    def execute(command, payload, folder, name, timeout):
        assert folder == root and name == "probe" and command[0] == "probe.py"
        (folder / "probe.stdout").write_bytes(b"ISOLATION_PROBE_OK\n")
        return {
            "exit_code": 0,
            "timed_out": False,
            "output_truncated": False,
            "stdout": str(sentinel),
        }

    def reader(path):
        assert path.parent == root
        protected.add(path.name)
        return path.read_bytes()

    monkeypatch.setattr("tempfile.TemporaryDirectory", refuse_legacy_temp)
    monkeypatch.setattr(verifier, "_cli", inspect)
    monkeypatch.setattr(verifier, "_execute", execute)
    assert verifier.preflight(diagnostics=root, read_bytes=reader)["probe"] == [
        "ISOLATION_PROBE_OK"
    ]
    assert protected == {"image.stdout", "host-canary.txt", "probe.stdout"}
    canary = root / "host-canary.txt"
    canary.write_bytes(b"previously owned canary")
    with pytest.raises(FileExistsError):
        verifier.preflight(diagnostics=root, read_bytes=reader)
    assert canary.read_bytes() == b"previously owned canary"
    assert sentinel.read_bytes() == b"outside"
    assert {p.name for p in tmp_path.iterdir()} == {"preflight", "outside.txt"}


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("invalid", "FAILED"),
        ("permissions", "UNKNOWN"),
        ("probe", "FAILED"),
        ("success", "COMPLETE"),
    ],
)
def test_study_pins_diagnostics_before_calculation(tmp_path, monkeypatch, failure, expected):
    verifier = SimpleNamespace(fingerprint="a" * 64, _ok=VerificationContainer._ok)
    plan, files = study.synthetic_job("first", verifier.fingerprint)
    job = tmp_path / "first"
    job.mkdir()
    diagnostics = job / "preflight"
    stack = []
    starts = []

    @contextmanager
    def directory(path, *, fresh, occupy):
        assert fresh and occupy
        if path == diagnostics:
            if failure == "invalid":
                raise ValueError("Study path encountered a reparse point")
            if failure == "permissions":
                raise PermissionError("denied")
        path.mkdir()
        stack.append(path)
        try:
            yield
        finally:
            assert stack.pop() == path

    def preflight(*, diagnostics, read_bytes):
        assert stack == [diagnostics, diagnostics / "docker-config"]
        if failure == "probe":
            raise IsolationUnavailable("probe failed")
        marker = diagnostics / "diagnostic.txt"
        with marker.open("xb") as f:
            f.write(b"owned diagnostic")
        assert read_bytes(marker) == b"owned diagnostic"
        return {"probe": ["ISOLATION_PROBE_OK"]}

    def execute(command, payload, folder, name, timeout):
        assert failure == "success" and folder == job and not stack
        starts.append(name)
        (job / "study.stdout").write_bytes(reseal(flat_export(plan)))
        record = {"exit_code": 0, "timed_out": False, "output_truncated": False}
        write_json(job / "study-cleanup.json", record)
        return record | {"duration_seconds": 0.01}

    def publish(path, raw, limit):
        assert path == job / "result.json"
        assert len(raw) < limit and not stack
        with path.open("xb") as f:
            f.write(raw)

    monkeypatch.setattr(study.storage, "directory", directory)
    monkeypatch.setattr(study.storage, "publish", publish)
    monkeypatch.setattr(study, "_bounded_bytes", lambda path, limit: path.read_bytes())
    monkeypatch.setattr(verifier, "preflight", preflight, raising=False)
    monkeypatch.setattr(verifier, "_execute", execute, raising=False)
    plan_sha = digest(files["plan.json"].decode())
    answer = study._run_reserved(verifier, job, plan, files, plan_sha)
    assert answer["status"] == expected
    bundle = _bundle(job)
    assert bundle["receipt"] == answer
    for _ in range(2):
        assert study._read_terminal(job / "result.json", plan, plan_sha) == answer
    if failure == "success":
        assert starts == ["study"] and bundle["stdout"] and study.PREFLIGHT in bundle["logs"]
        assert (diagnostics / "diagnostic.txt").read_bytes() == b"owned diagnostic"
    else:
        assert not starts and bundle["stdout"] is None and bundle["logs"] == {}


def test_receive_persists_and_replays_without_running_again(tmp_path, simulated):
    result = study.run_synthetic("first", tmp_path)
    assert result["status"] == "COMPLETE" and result["cleanup_confirmed"]
    assert study.run_synthetic("first", tmp_path) == result
    with pytest.raises(ValueError, match="different plan"):
        study.run_synthetic("first", tmp_path, timeout=61)
    job = tmp_path / "first"
    (job / "study.stdout").write_bytes(b"changed")
    (job / "study-cleanup.json").write_bytes(b"changed")
    assert study.run_synthetic("first", tmp_path) == result
    terminal = job / study.TERMINAL
    altered = terminal.read_bytes().replace(b'"COMPLETE"', b'"TIMED_OUT"', 1)
    terminal.write_bytes(altered)
    with pytest.raises(ValueError, match="integrity check failed"):
        study.run_synthetic("first", tmp_path)
    assert terminal.read_bytes() == altered
    assert simulated.starts == 1


def test_r1_swaps_spool_and_legacy_file_at_promotion(tmp_path, simulated, monkeypatch):
    decode = study.decode_result
    reads = []
    captured = []
    bounded = study._bounded_bytes
    rename = study.storage._rename

    def track(path, limit):
        if path.name == "study.stdout":
            reads.append(path)
            path.write_bytes(json.dumps(json.loads(path.read_bytes()), indent=2).encode() + b"\n")
        return bounded(path, limit)

    def inject(raw, plan):
        captured.append(raw)
        return decode(raw, plan)

    def swap(handle, path):
        if path.name == study.TERMINAL:
            (path.parent / "study.stdout").write_bytes(b"substituted spool")
            (path.parent / "accepted-stdout.json").write_bytes(b"substituted legacy artifact")
            assert not path.exists()
        return rename(handle, path)

    monkeypatch.setattr(study, "_bounded_bytes", track)
    monkeypatch.setattr(study.storage, "_rename", swap)
    with monkeypatch.context() as guarded:
        guarded.setattr(study, "decode_result", inject)
        outcome = study.run_synthetic("race", tmp_path)
    job = tmp_path / "race"
    assert reads == [job / "study.stdout"] and len(captured) == 1
    assert outcome["status"] == "COMPLETE"
    body = _bundle(job)
    assert body["receipt"] == outcome
    assert base64.b64decode(body["stdout"]) == captured[0]
    assert outcome["output_sha256"] == hashlib.sha256(captured[0]).hexdigest()
    assert study.run_synthetic("race", tmp_path) == outcome
    assert len(reads) == simulated.starts == 1


def test_capture_corruption_with_resealed_bundle_is_detected(tmp_path, simulated):
    study.run_synthetic("first", tmp_path)
    job = tmp_path / "first"
    body = _bundle(job)
    body["stdout"] = base64.b64encode(b"altered").decode()
    (job / study.TERMINAL).write_text(
        canonical({"body": body, "body_sha256": digest(canonical(body))}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="Accepted evidence SHA-256 changed"):
        study.run_synthetic("first", tmp_path)
    assert simulated.starts == 1


@pytest.mark.parametrize("kind", ["hardlink", "symlink"])
def test_linked_evidence_is_rejected_without_repeating(tmp_path, simulated, kind):
    study.run_synthetic("first", tmp_path)
    terminal = tmp_path / "first" / study.TERMINAL
    alias = tmp_path / "alias.json"
    try:
        if kind == "hardlink":
            os.link(terminal, alias)
        else:
            terminal.rename(alias)
            terminal.symlink_to(alias)
    except OSError:
        pytest.skip(f"This account cannot create a {kind} on the evidence volume")
    with pytest.raises((OSError, ValueError), match="links|reparse"):
        study.run_synthetic("first", tmp_path)
    assert simulated.starts == 1


@pytest.mark.skipif(os.name != "nt", reason="NTFS host evidence reader")
def test_stdout_limit_checked_before_read(tmp_path):
    path = tmp_path / "study.stdout"
    path.write_bytes(b" " * MAX_WIRE)
    with pytest.raises(ValueError, match="bounded regular evidence"):
        study._bounded_bytes(path, MAX_WIRE)


def test_r2_preserves_unowned_temp_on_collision(tmp_path, simulated, monkeypatch):
    rename = study.storage._rename
    token = "f" * 32
    monkeypatch.setattr(study.storage, "uuid4", lambda: SimpleNamespace(hex=token))
    foreign = tmp_path / "first" / f".{study.TERMINAL}.{token}.tmp"

    def install_foreign_temp(handle, path):
        rename(handle, path)
        if path.name == "reservation.json":
            foreign.write_bytes(b"other invocation")

    monkeypatch.setattr(study.storage, "_rename", install_foreign_temp)
    with pytest.raises(IsolationUncertain, match="Could not publish"):
        study.run_synthetic("first", tmp_path)
    assert foreign.read_bytes() == b"other invocation"
    assert not (foreign.parent / study.TERMINAL).exists()
    with pytest.raises(IsolationUncertain, match="interrupted reservation"):
        study.run_synthetic("first", tmp_path)
    assert simulated.starts == 1


def _junction(link, destination):
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(destination)],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _junction_in_place(path, destination, *, remove=False):
    storage = study.storage
    io_control = storage._bind(
        "DeviceIoControl",
        wintypes.BOOL,
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    )
    tag = 0xA0000003
    if remove:
        data = struct.pack("<IHH", tag, 0, 0)
    else:
        target = ("\\??\\" + str(destination)).encode("utf-16-le")
        display = str(destination).encode("utf-16-le")
        data = struct.pack(
            "<I6H",
            tag,
            12 + len(target) + len(display),
            0,
            0,
            len(target),
            len(target) + 2,
            len(display),
        )
        data += target + b"\0\0" + display + b"\0\0"
    handle = storage._open(path, 0x100, 7, storage.OPEN_EXISTING, 0x02000000)
    try:
        count = wintypes.DWORD()
        control = 0x900AC if remove else 0x900A4
        if not io_control(handle, control, data, len(data), None, 0, ctypes.byref(count), None):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        storage.close_handle(handle)


def test_r3_in_place_junction_before_first_anchor_never_writes_outside(
    tmp_path, simulated, monkeypatch
):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"untouched")
    root = tmp_path / "store"
    job = root / "first"
    open_native = study.storage._open_no_reparse

    def redirect(path, *args, **kwargs):
        if path == job / ".study-anchor":
            _junction_in_place(job, outside)
        return open_native(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(study.storage, "_open_no_reparse", redirect)
        try:
            with pytest.raises(ValueError, match="reparse"):
                study.run_synthetic("first", root)
            assert job.is_junction()
            assert list(outside.iterdir()) == [sentinel]
            assert sentinel.read_bytes() == b"untouched"
        finally:
            if job.is_junction():
                _junction_in_place(job, outside, remove=True)
    with pytest.raises(IsolationUncertain, match="interrupted reservation"):
        study.run_synthetic("first", root)
    assert simulated.starts == 0


def test_r3_rejects_real_junction_installed_before_directory_open(tmp_path, simulated, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"untouched")
    root = tmp_path / "store"
    root.mkdir()
    old = tmp_path / "previous"
    native_open = study.storage._open_no_reparse

    def substitute(path, *args, **kwargs):
        if path == root:
            root.rename(old)
            _junction(root, outside)
        return native_open(path, *args, **kwargs)

    monkeypatch.setattr(study.storage, "_open_no_reparse", substitute)
    try:
        with pytest.raises(ValueError, match="reparse"):
            study.run_synthetic("first", root)
        assert list(outside.iterdir()) == [sentinel]
        assert sentinel.read_bytes() == b"untouched" and simulated.starts == 0
    finally:
        if root.is_junction():
            root.rmdir()
    old.rename(root)
    monkeypatch.setattr(study.storage, "_open_no_reparse", native_open)
    assert study.run_synthetic("first", root)["status"] == "COMPLETE"


@pytest.mark.parametrize("scope", ["job", "root", "ancestor"])
def test_r3_pinned_directories_block_replacement_at_temp_open(
    tmp_path, simulated, monkeypatch, scope
):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"untouched")
    root = tmp_path / "parent" / "store"
    native_open = study.storage._open
    blocked = []

    def attempt_swap(path, *args):
        if path.name.startswith(".result.json."):
            victim = {"job": path.parent, "root": root, "ancestor": root.parent}[scope]
            moved = tmp_path / "moved"
            try:
                victim.rename(moved)
            except OSError as exc:
                assert exc.winerror in (5, 32)
                blocked.append(victim)
            else:
                _junction(victim, outside)
            with pytest.raises(OSError) as in_place:
                _junction_in_place(victim, outside)
            assert in_place.value.winerror == 145  # NTFS refuses a nonempty mount-point directory.
        return native_open(path, *args)

    monkeypatch.setattr(study.storage, "_open", attempt_swap)
    assert study.run_synthetic("first", root)["status"] == "COMPLETE"
    assert len(blocked) == 1
    assert list(outside.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"untouched"
    assert study.run_synthetic("first", root)["status"] == "COMPLETE"
    assert simulated.starts == 1


@pytest.mark.parametrize("failure", ["fsync", "existing_name", "rename_error"])
def test_publication_failure_leaves_no_partial_result(tmp_path, simulated, monkeypatch, failure):
    publish = study.storage.publish

    def broken(path, raw, limit):
        if path.name != study.TERMINAL:
            return publish(path, raw, limit)
        with monkeypatch.context() as patch:

            def fail(*_):
                raise OSError("Injected persistence failure")

            if failure == "fsync":
                patch.setattr(study.storage.os, "fsync", fail)
            elif failure == "rename_error":
                patch.setattr(study.storage, "_rename", fail)
            else:
                path.write_bytes(b"prior evidence")
            return publish(path, raw, limit)

    monkeypatch.setattr(study.storage, "publish", broken)
    with pytest.raises(IsolationUncertain, match="Could not publish"):
        study.run_synthetic("first", tmp_path)
    job = tmp_path / "first"
    if failure == "fsync":
        assert not list(job.glob("*.tmp"))
    if failure == "existing_name":
        assert (job / study.TERMINAL).read_bytes() == b"prior evidence"
        with pytest.raises(ValueError):
            study.run_synthetic("first", tmp_path)
    else:
        assert not (job / study.TERMINAL).exists()
        with pytest.raises(IsolationUncertain, match="interrupted reservation"):
            study.run_synthetic("first", tmp_path)
    assert simulated.starts == 1


@pytest.mark.parametrize("committed", [False, True])
def test_restart_resolves_ambiguous_promotion_without_new_execution(
    tmp_path, simulated, monkeypatch, committed
):
    rename = study.storage._rename

    def interrupt(handle, path):
        if path.name != study.TERMINAL:
            return rename(handle, path)
        if committed:
            rename(handle, path)
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(study.storage, "_rename", interrupt)
        with pytest.raises(KeyboardInterrupt):
            study.run_synthetic("first", tmp_path)
    job = tmp_path / "first"
    assert (job / "reservation.json").exists()
    if committed:
        assert study.run_synthetic("first", tmp_path)["status"] == "COMPLETE"
    else:
        assert not (job / study.TERMINAL).exists()
        with pytest.raises(IsolationUncertain):
            study.run_synthetic("first", tmp_path)
        with pytest.raises(IsolationUncertain):
            study.run_synthetic("second", tmp_path)
    assert simulated.starts == 1


@pytest.mark.parametrize("committed", [False, True])
def test_real_process_exit_at_publication(tmp_path, simulated, committed):
    program = """
import os
import runpy
import sys
from pathlib import Path
from pytest import MonkeyPatch
from trading_lab_orchestration import isolated_study as study

fixture = runpy.run_path(sys.argv[1])["simulated"]
patch = MonkeyPatch()
verifier = fixture.__wrapped__(patch)
rename = study.storage._rename

def exit_at_rename(handle, path):
    if path.name != study.TERMINAL:
        return rename(handle, path)
    assert verifier.starts == 1
    if sys.argv[3] == "1":
        rename(handle, path)
    os._exit(73)

study.storage._rename = exit_at_rename
study.run_synthetic("first", Path(sys.argv[2]))
"""
    child = subprocess.run(
        [sys.executable, "-B", "-c", program, __file__, str(tmp_path), str(int(committed))],
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert child.returncode == 73, child.stderr
    if committed:
        assert study.run_synthetic("first", tmp_path)["status"] == "COMPLETE"
    else:
        with pytest.raises(IsolationUncertain, match="interrupted reservation"):
            study.run_synthetic("first", tmp_path)
    assert simulated.starts == 0


@pytest.mark.parametrize(
    "outcome,status",
    [
        ("timeout", "TIMED_OUT"),
        ("invalid", "FAILED"),
        ("uncertain", "UNKNOWN"),
        ("interrupt", "UNKNOWN"),
    ],
)
def test_failure_timeout_interruption_and_uncertainty_are_persisted(
    outcome, status, tmp_path, simulated
):
    simulated.outcome = outcome
    if outcome == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            study.run_synthetic("first", tmp_path)
    else:
        assert study.run_synthetic("first", tmp_path)["status"] == status
    recovered = study.run_synthetic("first", tmp_path)
    assert recovered["status"] == status and "export" not in recovered
    if status == "UNKNOWN":
        with pytest.raises(IsolationUncertain):
            study.run_synthetic("next", tmp_path)
    assert simulated.starts == 1


def test_duplicate_concurrent_execution_blocked(tmp_path, simulated):
    simulated.wait = Event()
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(study.run_synthetic, "same", tmp_path)
        try:
            assert simulated.started.wait(timeout=10)
            with pytest.raises(ValueError, match="owns the OS lock"):
                study.run_synthetic("same", tmp_path)
        finally:
            simulated.wait.set()
        assert future.result()["status"] == "COMPLETE"
    assert simulated.starts == 1


def test_abrupt_restart_keeps_unresolved_reservation(tmp_path, simulated):
    (tmp_path / "first").mkdir()
    with pytest.raises(IsolationUncertain, match="interrupted reservation"):
        study.run_synthetic("other", tmp_path)
    assert simulated.starts == 0


def test_only_frozen_synthetic_inputs_are_executable(plan, tmp_path, simulated):
    with pytest.raises(ValueError):
        study.run_synthetic("../outside", tmp_path)
    with pytest.raises(TypeError):
        study.run_synthetic("safe", tmp_path, dataset="historical")
    with pytest.raises(ValueError, match="synthetic"):
        Plan.model_validate(plan.model_dump() | {"holdout": "CONSUMED"})
    simulated.image = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="Approved verifier image"):
        study.run_synthetic("first", tmp_path)
    assert simulated.starts == 0


@pytest.mark.parametrize(
    "bad",
    [
        "../x.json",
        "/etc/passwd",
        "cases\\unsafe.json",
        "unexpected.py",
        "cases/x.json",
        "cases/x.pkl",
    ],
)
def test_rejects_unexpected_and_unsafe_members(plan, bad):
    exported = flat_export(plan)
    exported["files"][bad] = next(iter(exported["files"].values()))
    exported["sha256"][bad] = digest(canonical(exported["files"][bad]))
    with pytest.raises(ValueError, match="unsafe result paths"):
        decode_result(canonical(exported).encode(), plan)


@pytest.mark.parametrize("kind", ["hash", "identity", "metrics", "types", "missing", "schema"])
def test_rejects_inconsistent_evidence(plan, kind):
    exported = flat_export(plan)
    name, case = next(iter(exported["files"].items()))
    if kind == "hash":
        exported["sha256"][name] = "0" * 64
    if kind == "identity":
        exported["plan_sha256"] = "0" * 64
    if kind == "metrics":
        case["equity"][-1] += 5
        exported["sha256"][name] = digest(canonical(case))
    if kind == "types":
        case["metrics"]["closed_trades"] = "0"
    if kind == "missing":
        exported["files"].pop(name)
    if kind == "schema":
        exported["schema_version"] = "2.0"
    with pytest.raises(ValueError):
        decode_result(canonical(exported).encode(), plan)


def test_wire_limits_and_unambiguous_json(plan):
    assert decode_result(canonical(flat_export(plan)).encode(), plan).status == "COMPLETE"
    for raw in (b'{"x":NaN}', b'{"x":0,"x":1}', b" " * MAX_WIRE, b"{"):
        with pytest.raises(ValueError):
            decode_result(raw, plan)


def test_rejects_original_flat_account_attack(plan, tmp_path, simulated):
    raw = corrupt_flat(flat_export(plan))
    with pytest.raises(SemanticInconsistency, match="REJECTED_SEMANTIC_INCONSISTENCY"):
        decode_result(raw, plan)
    simulated.outcome = "manipulated"
    result = study.run_synthetic("flat_attack", tmp_path)
    assert result["status"] == "FAILED" and "export" not in result
    assert "REJECTED_SEMANTIC_INCONSISTENCY" in result["reason"]


@pytest.mark.parametrize(
    "mutation",
    [
        "equity",
        "exposure",
        "removed_trade",
        "duplicated_trade",
        "quantity",
        "commission",
        "entry_price",
        "exit_price",
        "exit_timestamp",
        "duplicate_rejection",
        "undeclared_position",
        "metrics",
        "coherent_forgery",
    ],
)
def test_semantic_mutations_reach_accounting_validator(plan, valid_export, mutation):
    case = valid_export["files"][BASE_CASE]
    trade = case["trades"][0]
    if mutation == "equity":
        case["equity"][3] += 0.25
    elif mutation == "exposure":
        case["exposure"][3] *= 2
    elif mutation == "removed_trade":
        case["trades"].pop(0)
    elif mutation == "duplicated_trade":
        case["trades"].insert(1, trade.copy())
    elif mutation in {"quantity", "entry_price", "exit_price"}:
        trade[mutation] *= 1.01
    elif mutation == "commission":
        trade["entry_fee"] = 0.0
    elif mutation == "exit_timestamp":
        trade["exit_time"] = trade["exit_bar_open"]
    elif mutation == "duplicate_rejection":
        when = (plan.cases[0].start + timedelta(hours=1)).isoformat()
        case["rejections"] = [{"time": when, "reason": "below_min_notional"}] * 2
        case["metrics"]["rejected_entries"] = 2
    elif mutation == "undeclared_position":
        case["trades"].pop()
        case["exposure"][-1] = case["exposure"][-2]
    elif mutation == "metrics":
        case["metrics"]["profit_factor"] += 1
    elif mutation == "coherent_forgery":
        # Change the ledger, fills and summary together as if a signal had sold below the open.
        trade = case["trades"][-1]
        change = 0.5
        trade["exit_reference"] -= change
        _update_exit_accounting(case, trade)
        refresh_metrics(case)
    with pytest.raises(SemanticInconsistency):
        decode_result(reseal(valid_export), plan)


def _update_exit_accounting(case, trade):
    costs = case["costs"]
    slip = costs["slippage_pct"] / 100
    spread = costs["spread_pct"] / 200
    trade["exit_price"] = trade["exit_reference"] * (1 - slip - spread)
    trade["exit_fee"] = trade["quantity"] * trade["exit_price"] * costs["trading_fee_pct"] / 100
    trade["net_pnl"] = (
        trade["quantity"] * (trade["exit_price"] - trade["entry_price"])
        - trade["entry_fee"]
        - trade["exit_fee"]
    )
    reference_notional = trade["quantity"] * (trade["entry_reference"] + trade["exit_reference"])
    trade["slippage_cost"] = reference_notional * slip
    trade["spread_cost"] = reference_notional * spread
    case["equity"][-1] = case["equity"][0] + sum(t["net_pnl"] for t in case["trades"])


def test_legitimate_intrabar_losses_fees_and_mark_to_market(plan, valid_export):
    case = decode_result(reseal(valid_export), plan).files[BASE_CASE]
    first = case.trades[0]
    assert first.exit_timing == "intrabar" and first.exit_time is None
    assert case.equity[3] < case.equity[0] and case.exposure[3] > 0
    assert case.equity[5] > case.equity[3] and case.exposure[5] > 0
    assert case.trades[1].net_pnl < 0 and case.trades[1].reason == "stop"


def test_legitimate_final_liquidation(plan, valid_export):
    case = valid_export["files"][BASE_CASE]
    trade = case["trades"][-1]
    last_open = datetime.fromisoformat(trade["exit_bar_open"])
    trade.update(
        exit_reference=json.loads(synthetic_fixture())["ohlcv"][-1][3],
        exit_time=(last_open + timedelta(hours=1)).isoformat(),
        exit_timing="close",
        reason="end_of_study",
        holding_bars=trade["holding_bars"] + 1,
    )
    _update_exit_accounting(case, trade)
    refresh_metrics(case)
    assert (
        decode_result(reseal(valid_export), plan).files[BASE_CASE].trades[-1].reason
        == "end_of_study"
    )


def test_historical_proposal_is_frozen_and_has_no_execution_entrypoint():
    path = (
        Path(__file__).resolve().parents[2]
        / "examples/orchestration/phase-5-5a/historical-authorization.draft.json"
    )
    draft = json.loads(path.read_bytes())
    assert draft["status"] == "DRAFT_NO_OPERATOR_CONFIRMATION"
    plan = Plan.model_validate_json(canonical(draft["plan"]))
    assert plan.kind == "HISTORICAL_PROPOSAL" and plan.holdout == "CONSUMED"
    assert [c.bars for c in plan.cases] == [1416, 1416, 720, 720, 744, 744]
    draft["plan"]["cases"][0]["warmup"] = 239
    with pytest.raises(ValueError, match="frozen case"):
        Plan.model_validate_json(canonical(draft["plan"]))


@pytest.mark.skipif(
    os.environ.get("TRADING_LAB_55A_REAL_ISOLATION_TEST") != "1",
    reason="Explicit synthetic acceptance with the pinned Docker Linux image",
)
def test_real_synthetic_study_in_docker(tmp_path):
    record = study.run_synthetic("docker_acceptance", tmp_path)
    assert record["status"] == "COMPLETE", record
    assert record["cleanup_confirmed"]
    job = tmp_path / "docker_acceptance"
    diagnostics = job / "preflight"
    for name in ("image.stdout", "probe.stdout", "probe-cleanup.json", "host-canary.txt"):
        assert (diagnostics / name).is_file() and not (job / name).exists()
    assert (diagnostics / "docker-config" / ".study-anchor").is_file()
    assert len(record["export"]["files"]) == 2
    for case in record["export"]["files"].values():
        assert case["metrics"]["closed_trades"] >= 2
        assert "target" in {trade["reason"] for trade in case["trades"]}
        assert "stop" in {trade["reason"] for trade in case["trades"]}
    probe = json.loads(base64.b64decode(_bundle(job)["logs"][study.PREFLIGHT]))
    for label in ("external write", "external TCP", "external DNS", "VM-to-host socket"):
        assert probe["probe"].count(f"{label}: blocked") == 2
    assert study.run_synthetic("docker_acceptance", tmp_path) == record


@pytest.mark.skipif(
    os.environ.get("TRADING_LAB_55A_REAL_ISOLATION_TEST") != "1",
    reason="Explicit Docker deadline acceptance",
)
def test_real_docker_deadline_confirms_cleanup(tmp_path):
    verifier = VerificationContainer()
    outcome = verifier._execute(
        ["-c", "import time; time.sleep(90)"], _payload({}), tmp_path, "deadline", 10
    )
    assert outcome["timed_out"]
    cleanup = json.loads((tmp_path / "deadline-cleanup.json").read_bytes())
    assert verifier._ok(cleanup)
