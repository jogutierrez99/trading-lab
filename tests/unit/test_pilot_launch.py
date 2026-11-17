import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_pilot_authorization import case as case
from test_pilot_authorization import grant, prepare

from trading_lab_orchestration import codex_adapter, implementation, pilot_launch
from trading_lab_orchestration.contracts import HypothesisManifest, canonical, digest
from trading_lab_orchestration.execution import Executor
from trading_lab_orchestration.github_intake import parse_proposal
from trading_lab_orchestration.store import Store
from trading_lab_orchestration.workspaces import changes, create_workspace, git

ROOT = Path(__file__).resolve().parents[2]


class SimulatedVerifier:
    fingerprint = "1" * 64

    def preflight(self):
        return {"verification_sha256": self.fingerprint, "simulated": True}


@pytest.fixture
def ready(case, monkeypatch):
    def workspace(attempt, paths):
        create_workspace(attempt, paths)
        for path in paths:
            output = Path(attempt["workspace"]) / path
            output.parent.mkdir(parents=True, exist_ok=True)
            text = (
                f"name: {output.stem}\nenabled: false\n" if output.suffix == ".yaml" else "# frozen"
            )
            output.write_text(text, encoding="utf-8")

    monkeypatch.setattr(implementation, "create_workspace", workspace)
    monkeypatch.setattr(implementation, "changes", changes)
    pre = grant(case)
    attempt = prepare(case, pre)
    assert attempt["status"] == "PREPARED"
    monkeypatch.setattr(
        pilot_launch, "current_operator", lambda: (case[-1].approved_by, case[-1].operator_sid)
    )
    monkeypatch.setattr(pilot_launch, "check_live_issue", lambda *_: None)
    monkeypatch.setattr(pilot_launch, "VerificationContainer", SimulatedVerifier)
    monkeypatch.setattr(implementation, "VerificationContainer", SimulatedVerifier)
    return case[0], case[1], attempt, pre


def approve(ready, monkeypatch, response=None):
    coordinator, _, attempt, _ = ready
    terminal = SimpleNamespace(isatty=lambda: True)
    monkeypatch.setattr(pilot_launch, "sys", SimpleNamespace(stdin=terminal, stdout=terminal))
    challenge = f"LANZAR {attempt['attempt_id']} {attempt['controls_sha256']}"
    monkeypatch.setattr("builtins.input", lambda _: challenge if response is None else response)
    return pilot_launch.approve_launch(
        coordinator.store.path, coordinator, attempt["attempt_id"], None
    )


def mock_adapter(ready, monkeypatch, behavior=None):
    starts = []

    class FakeCLI:
        omit_env = ()

        def __init__(self, executable, *, windows_sandbox):
            assert (executable, windows_sandbox) == ("codex", "mxc")

        def probe(self, workspace, *, require_chatgpt):
            assert require_chatgpt
            return {"simulated": True}

        def argv(self, *paths):
            return ["fake-codex", "--sandbox", "workspace-write"]

    def process(argv, workspace, timeout, stdout, stderr, prompt, on_start, **kwargs):
        assert argv == ["fake-codex", "--sandbox", "workspace-write"]
        assert timeout == 600 and "independently authorized one launch" in prompt
        starts.append(argv)
        assert ready[0].attempt(ready[2]["attempt_id"])["status"] == "RUNNING"
        if behavior:
            behavior()
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return {"timed_out": False, "exit_code": 1}

    monkeypatch.setattr(implementation, "CodexCLI", FakeCLI)
    monkeypatch.setattr(implementation, "run_process", process)
    return starts


def state(ready, identifier):
    with ready[0].store.connection() as conn:
        row, receipt = pilot_launch.read_launch(conn, identifier)
        assert row["receipt_sha256"] == digest(canonical(receipt.model_dump(mode="json")))
        return row["state"], receipt


def launch(ready, identifier):
    return ready[0].run(
        ready[2]["attempt_id"], pilot_launch=pilot_launch.PilotLaunch(identifier, None)
    )


@pytest.mark.parametrize("changed", [True, False])
def test_unavailable_or_changed_verifier_prevents_reservation(ready, monkeypatch, changed):
    identifier = approve(ready, monkeypatch)["authorization_id"]
    starts = mock_adapter(ready, monkeypatch)

    def probe(self):
        if changed:
            return {"verification_sha256": "2" * 64}
        raise implementation.IsolationUnavailable("Container unavailable")

    monkeypatch.setattr(SimulatedVerifier, "preflight", probe)
    with pytest.raises(ValueError, match="Verifier configuration changed|Container unavailable"):
        launch(ready, identifier)
    assert not starts
    assert state(ready, identifier)[0] == "APPROVED"
    assert ready[0].attempt(ready[2]["attempt_id"])["status"] == "PREPARED"


def test_independent_confirmation_and_consumption(ready, monkeypatch):
    coordinator, ledger, attempt, pre_id = ready
    with pytest.raises(ValueError, match="LAUNCH_AUTHORIZATION_NOT_ENABLED"):
        coordinator.run(attempt["attempt_id"])
    with pytest.raises(ValueError, match="LAUNCH_AUTHORIZATION_NOT_ENABLED"):
        launch(ready, pre_id)
    with pytest.raises(ValueError, match="confirmation did not match"):
        approve(ready, monkeypatch, response="PREPARE_ONLY")
    grant = approve(ready, monkeypatch)
    identifier = grant["authorization_id"]
    launch_state, receipt = state(ready, identifier)
    assert launch_state == "APPROVED" and receipt.permission == "LAUNCH_CODEX"
    assert receipt.preparation_authorization_id == pre_id and not receipt.backtests_allowed
    assert receipt.max_api_eur == 0 and not receipt.repair_allowed
    with (
        pytest.raises(sqlite3.IntegrityError, match="no launch authorization"),
        coordinator.store.transaction() as conn,
    ):
        conn.execute(
            "UPDATE attempts SET status='RUNNING' WHERE attempt_id=?", (attempt["attempt_id"],)
        )
    starts = mock_adapter(ready, monkeypatch)
    original_ledger = ledger.store.path.read_bytes()
    assert launch(ready, identifier)["status"] == "FAILED"
    assert state(ready, identifier)[0] == "CONSUMED"
    with pytest.raises(ValueError, match="unavailable"):
        launch(ready, identifier)
    assert len(starts) == 1 and ledger.store.path.read_bytes() == original_ledger
    assert not coordinator.attempt(attempt["attempt_id"])["retry_allowed"]
    with pytest.raises(ValueError, match="LAUNCH_AUTHORIZATION_NOT_ENABLED"):
        coordinator.repair_format(attempt["attempt_id"], True, "fixture")
    with pytest.raises(ValueError, match="separate backtest authorization"):
        Executor(coordinator.store).prepare(attempt["attempt_id"], None, None)


@pytest.mark.parametrize(
    "scenario", ["request", "commit", "files", "enabled", "ledger", "other_work"]
)
def test_revalidation_blocks_without_consuming(ready, monkeypatch, scenario):
    coordinator, ledger, attempt, _ = ready
    identifier = approve(ready, monkeypatch)["authorization_id"]
    work = Path(attempt["workspace"])
    _, receipt = state(ready, identifier)
    if scenario == "request":
        (Path(attempt["root"]) / "request.json").write_text("{}", encoding="utf-8")
    elif scenario == "commit":
        git(
            work,
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "changed",
        )
    elif scenario in {"files", "enabled"}:
        path = work / f"configs/strategies/{receipt.task_id}.yaml"
        if scenario == "enabled":
            (path,) = (work / "configs/strategies").glob("*.yaml")
        path.write_text("enabled: true", encoding="utf-8")
    elif scenario == "ledger":
        ledger.store.path.rename(ledger.store.path.with_suffix(".unavailable"))
    elif scenario == "other_work":
        manifest = parse_proposal(
            (ROOT / "examples/orchestration/phase-5-4b/issue-body.json").read_text(encoding="utf-8")
        ).manifest.model_dump(mode="json")
        manifest.update(hypothesis_id="other_case", market_hypothesis="Separate fixture")
        manifest["signal_spec"]["long_entry"] = "Other entry"
        task = coordinator.store.register(
            HypothesisManifest.model_validate_json(canonical(manifest))
        )["task_id"]
        with coordinator.store.transaction() as conn:
            conn.execute(
                """INSERT INTO attempts (
                attempt_id,task_id,number,status,repo,root,workspace,branch,base_commit,created_at_utc
                ) VALUES ('other_attempt',?,1,'CANCELLED','repo','root','workspace','branch',?,
                          'fixture')""",
                (task, attempt["base_commit"]),
            )
            conn.execute(
                """INSERT INTO executions (
                execution_id,task_id,attempt_id,intent_sha256,status,root,created_at_utc
                ) VALUES ('other',?,'other_attempt',?,'UNKNOWN','other','fixture')""",
                (task, "b" * 64),
            )
    starts = mock_adapter(ready, monkeypatch)
    with pytest.raises((ValueError, FileNotFoundError)):
        launch(ready, identifier)
    assert state(ready, identifier)[0] == "APPROVED"
    assert not starts


def test_launch_permission_cannot_target_another_attempt(ready, monkeypatch):
    identifier = approve(ready, monkeypatch)["authorization_id"]
    row = ready[2] | {"attempt_id": "another_attempt"}
    with ready[0].store.connection() as conn:
        with pytest.raises(ValueError, match="another attempt"):
            pilot_launch.validate_launch(
                conn, ready[0], row, pilot_launch.PilotLaunch(identifier, None)
            )


def test_lazy_schema_upgrade_preserves_old_queue_and_seals_receipts(ready, monkeypatch, tmp_path):
    coordinator, ledger, attempt, prep_id = ready
    source = coordinator.store.path
    original = source.read_bytes()
    copied = tmp_path / "migration.sqlite3"
    with coordinator.store.connection() as conn, sqlite3.connect(copied) as backup:
        conn.backup(backup)
    isolated = implementation.Coordinator(Store(copied))
    with isolated.store.connection() as conn:
        assert pilot_launch.launch_for_attempt(conn, attempt["attempt_id"]) is None
    fixture = isolated, ledger, attempt, prep_id
    identifier = approve(fixture, monkeypatch)["authorization_id"]
    assert source.read_bytes() == original
    assert isolated.attempt(attempt["attempt_id"]) == attempt
    with isolated.store.connection() as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA recursive_triggers").fetchone()[0] == 0
    for sql, value, message in (
        (
            "UPDATE pilot_launch_authorizations SET state='RESERVED' WHERE authorization_id=?",
            identifier,
            "requires its audit event",
        ),
        (
            "INSERT OR REPLACE INTO pilot_launch_authorizations SELECT * "
            "FROM pilot_launch_authorizations WHERE authorization_id=?",
            identifier,
            "already exists",
        ),
        (
            "INSERT OR REPLACE INTO pilot_authorizations SELECT * FROM pilot_authorizations "
            "WHERE authorization_id=?",
            prep_id,
            "already exists",
        ),
        (
            "UPDATE attempts SET controls_sha256='changed' WHERE attempt_id=?",
            attempt["attempt_id"],
            "sealed launch attempt",
        ),
        (
            "INSERT OR REPLACE INTO attempts SELECT * FROM attempts WHERE attempt_id=?",
            attempt["attempt_id"],
            "sealed launch attempt",
        ),
    ):
        with (
            pytest.raises(sqlite3.IntegrityError, match=message),
            isolated.store.transaction() as conn,
        ):
            conn.execute(sql, (value,))
    assert state(fixture, identifier)[0] == "APPROVED"


def test_hard_exit_after_reservation_before_spawning(ready, monkeypatch):
    coordinator, _, attempt, _ = ready
    identifier = approve(ready, monkeypatch)["authorization_id"]
    code = """
import os, sys
from pathlib import Path
from types import SimpleNamespace
from trading_lab_orchestration import implementation, pilot_launch
from trading_lab_orchestration.store import Store
pilot_launch.current_operator = lambda: tuple(sys.argv[4:6])
pilot_launch.check_live_issue = lambda *_: None
implementation.CodexCLI = lambda *a, **kw: SimpleNamespace(probe=lambda *a, **kw: {})
class SimulatedVerifier:
    fingerprint = '1' * 64
    def preflight(self):
        return {'verification_sha256': self.fingerprint}
pilot_launch.VerificationContainer = implementation.VerificationContainer = SimulatedVerifier
implementation.write_json = lambda *a, **kw: os._exit(77)
implementation.run_process = lambda *a, **kw: os._exit(99)
implementation.Coordinator(Store(Path(sys.argv[1]))).run(
    sys.argv[2], pilot_launch=pilot_launch.PilotLaunch(sys.argv[3], None))
"""
    operator, sid = pilot_launch.current_operator()
    child = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            code,
            str(coordinator.store.path),
            attempt["attempt_id"],
            identifier,
            operator,
            sid,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert child.returncode == 77, child.stderr
    assert state(ready, identifier)[0] == "RESERVED"
    actual = coordinator.attempt(attempt["attempt_id"])
    assert actual["status"] == "RUNNING" and actual["child_pid"] is None
    assert not (Path(attempt["root"]) / "codex.jsonl").exists()
    with pytest.raises(ValueError, match="unavailable"):
        launch(ready, identifier)
    assert coordinator.inspect(attempt["attempt_id"])["status"] == "UNKNOWN"
    assert state(ready, identifier)[0] == "UNKNOWN"


@pytest.mark.parametrize(("implemented", "isolated"), [(False, False), (True, False), (True, True)])
def test_success_requires_verified_delivery(ready, monkeypatch, implemented, isolated):
    coordinator, _, attempt, _ = ready
    identifier = approve(ready, monkeypatch)["authorization_id"]
    mock_adapter(ready, monkeypatch)
    request = coordinator._request(attempt)
    root = Path(attempt["root"])
    checks = []

    def process(argv, workspace, timeout, stdout, stderr, *args, **kwargs):
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        if argv[0] == "fake-codex":
            if implemented:
                (workspace / request.allowed_write_paths[0]).write_text(
                    "# Simulated implementation", encoding="utf-8"
                )
            fields = (
                "candidate_id",
                "task_id",
                "attempt_id",
                "hypothesis_sha256",
                "base_commit",
                "branch",
            )
            delivery = {name: getattr(request, name) for name in fields}
            delivery.update(
                schema_version="1.0",
                status="IMPLEMENTED",
                summary="Fixture",
                files=[dict(path=p, sha256=h) for p, h in changes(attempt).items()],
                tests_run="NOT_RUN_BY_MODEL",
                warnings=[],
                blockers=[],
                prepared_commands=[],
            )
            (root / "delivery.json").write_text(json.dumps(delivery), encoding="utf-8")
        else:
            pytest.fail("Pilot verification reached the host process supervisor directly")
        return dict(exit_code=0, timed_out=False, duration_seconds=0)

    def verify(_self, request, files, actual, evidence, deadline):
        checks.extend(command[1:] for command in request.authorized_checks)
        if not isolated:
            raise implementation.IsolationUnavailable("Simulated failure of containment")
        return [], {"mode": "simulated"}

    monkeypatch.setattr(implementation, "run_process", process)
    monkeypatch.setattr(SimulatedVerifier, "verify", verify, raising=False)
    result = launch(ready, identifier)
    expected = "FAILED" if not implemented else "SUCCEEDED" if isolated else "BLOCKED"
    assert result["status"] == expected
    assert state(ready, identifier)[0] == "CONSUMED" and not result["retry_allowed"]
    if implemented:
        assert checks == [command[1:] for command in request.authorized_checks]
    if isolated:
        evidence = json.loads(Path(result["error"].removeprefix("Verified receipt: ")).read_bytes())
        assert evidence["status"] == "IMPLEMENTED_VERIFIED"
        assert evidence["launch_authorization"]["authorization_id"] == identifier
        assert evidence["launch_authorization"]["verification_sha256"] == "1" * 64
    else:
        assert not list(root.glob("verification_*/receipt.json"))


def test_concurrent_launches_reserve_once(ready, monkeypatch):
    identifier = approve(ready, monkeypatch)["authorization_id"]
    starts = mock_adapter(ready, monkeypatch)

    def run():
        try:
            return launch(ready, identifier)["status"]
        except ValueError:
            return "REFUSED"

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(run), workers.submit(run)]
        assert sorted(f.result(timeout=20) for f in futures) == ["FAILED", "REFUSED"]
    assert len(starts) == 1 and state(ready, identifier)[0] == "CONSUMED"


def test_interrupted_launch_closes_without_replay(ready, monkeypatch):
    identifier = approve(ready, monkeypatch)["authorization_id"]

    def interrupt():
        raise KeyboardInterrupt

    starts = mock_adapter(ready, monkeypatch, interrupt)
    with pytest.raises(KeyboardInterrupt):
        launch(ready, identifier)
    assert state(ready, identifier)[0] == "UNKNOWN"
    assert ready[0].attempt(ready[2]["attempt_id"])["status"] == "UNKNOWN"
    with pytest.raises(ValueError, match="stopped confirmation"):
        pilot_launch.close_launch(ready[0], identifier, "simulated")
    name = "tl-pilot-verify-" + "1" * 32
    evidence = Path(ready[2]["root"]) / "verification_simulated"
    evidence.mkdir()
    (evidence / "check-0-container.json").write_text(
        json.dumps({"container": name}), encoding="utf-8"
    )
    checked = []

    def confirm_cleanup(self, container):
        checked.append(container)
        if len(checked) == 1:
            raise implementation.IsolationUnavailable("Container absence not confirmed")

    monkeypatch.setattr(SimulatedVerifier, "confirm_cleanup", confirm_cleanup, raising=False)
    with pytest.raises(ValueError, match="absence not confirmed"):
        pilot_launch.close_launch(ready[0], identifier, "simulated", confirm_stopped=True)
    assert state(ready, identifier)[0] == "UNKNOWN"
    result = pilot_launch.close_launch(ready[0], identifier, "simulated", confirm_stopped=True)
    assert result["status"] == "CANCELLED" and state(ready, identifier)[0] == "CLOSED"
    assert checked == [name, name]
    with pytest.raises(ValueError, match="unavailable"):
        launch(ready, identifier)
    assert len(starts) == 1


def test_legacy_cli_and_noninteractive_approval_refused(ready):
    a = ready[2]["attempt_id"]
    db = str(ready[0].store.path)
    for script, command, marker in (
        ("orchestrator.py", ["run", a], "LAUNCH_AUTHORIZATION_NOT_ENABLED"),
        ("authorize_github_pilot.py", ["approve-launch", "--attempt-id", a], "interactive Windows"),
    ):
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts" / script), "--db", db, *command],
            input="approve\n",
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 2 and marker in result.stdout
    with ready[0].store.connection() as conn:
        assert pilot_launch.launch_for_attempt(conn, a) is None


@pytest.mark.parametrize(
    "status,allowed",
    [
        ("Logged in using an API key", False),
        ("Logged in using ChatGPT", True),
    ],
)
def test_pilot_rejects_api_key_authentication(tmp_path, monkeypatch, status, allowed):
    monkeypatch.setattr(codex_adapter.shutil, "which", lambda _: str(tmp_path / "codex.exe"))
    stdout = iter(("fixture", " ".join(codex_adapter.REQUIRED_FLAGS), status))
    monkeypatch.setattr(
        codex_adapter.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=next(stdout), stderr=""),
    )
    cli = codex_adapter.CodexCLI("codex")
    if allowed:
        assert cli.probe(tmp_path, require_chatgpt=True)["authenticated"]
    else:
        with pytest.raises(codex_adapter.PreflightError, match="using ChatGPT"):
            cli.probe(tmp_path, require_chatgpt=True)
