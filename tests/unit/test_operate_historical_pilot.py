import importlib.util
import json
import os
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from trading_lab_orchestration import historical_pilot as pilot
from trading_lab_orchestration import historical_pilot_store as store


@pytest.fixture
def cli_module():
    path = Path(__file__).resolve().parents[2] / "scripts/operate_historical_pilot.py"
    spec = importlib.util.spec_from_file_location("historical_operator", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    return cli


@pytest.fixture
def fixture(tmp_path, monkeypatch, cli_module):
    cli = cli_module
    registry = tmp_path / "registry"
    scratch = tmp_path / "scratch"
    registry.mkdir()
    scratch.mkdir()
    database = registry / pilot.DB
    args = [
        "--checkout-commit",
        cli.BASE_COMMIT,
        "--data-repo",
        str(tmp_path / "data"),
        "--coordinator-db",
        str(tmp_path / "operational/queue.sqlite3"),
        "--registry",
        str(registry),
        "--scratch",
        str(scratch),
    ]
    operator = ("fixture", "S-1-5-21-123")
    attempt = f"attempt_{'1' * 32}"
    job = SimpleNamespace(
        plan=SimpleNamespace(
            cases=[
                SimpleNamespace(id=key)
                for key in (
                    "train_base",
                    "train_adverse",
                    "validation_base",
                    "validation_adverse",
                    "test_retrospective_base",
                    "test_retrospective_adverse",
                )
            ],
            limits=SimpleNamespace(model_dump=lambda **kwargs: {"max_cases": 6}),
        ),
        model_dump=lambda **kwargs: {"fixture": True},
    )
    calls = []
    monkeypatch.setattr(cli, "_checkout", lambda *_: None)
    monkeypatch.setattr(cli, "_require_designated_registry", lambda *_: None)
    monkeypatch.setattr(cli, "_windows_acl", lambda *_: None)
    monkeypatch.setattr(cli, "_inspect_image", lambda *_: None)
    monkeypatch.setattr(cli, "_interactive", lambda: None)
    terminal = SimpleNamespace(isatty=lambda: True)
    monkeypatch.setattr(pilot, "sys", SimpleNamespace(stdin=terminal, stdout=terminal))
    monkeypatch.setattr(cli.ntfs, "pinned_root", lambda root, **_: nullcontext(root))
    monkeypatch.setattr(cli.ntfs, "exclusive_lock", lambda _: nullcontext())
    monkeypatch.setattr(cli.ntfs, "_open_no_reparse", lambda *_, **__: 123)
    monkeypatch.setattr(cli.ntfs, "_info", lambda *_, **__: None)
    monkeypatch.setattr(cli.ntfs, "close_handle", lambda _: None)
    monkeypatch.setattr(pilot, "_paths", lambda *_: None)
    monkeypatch.setattr(pilot, "HistoricalVerifier", lambda: SimpleNamespace(image="fixture"))
    monkeypatch.setattr(
        pilot,
        "prepare",
        lambda *_, **__: (job, {}, {"parquet_sha256": "p", "manifest_sha256": "m"}),
    )
    monkeypatch.setattr(pilot, "plan_sha", lambda _: cli.JOB_SHA256)
    monkeypatch.setattr(
        pilot, "_verified_binding", lambda _: (attempt, cli.RECEIPT_SHA256, *operator)
    )

    # Keep the real approval, schema, integrity checks and one-shot transaction.
    permit = store.Permit(
        purpose="HISTORICAL_BACKTEST_ONCE",
        attempt_id=attempt,
        implementation_receipt_sha256=cli.RECEIPT_SHA256,
        job_sha256=cli.JOB_SHA256,
        operator=operator[0],
        operator_sid=operator[1],
        approved_at=cli.datetime.now(cli.UTC),
    )
    monkeypatch.setattr(pilot, "authorization_proposal", lambda *_: (permit, job, {}))

    def run(_data, _queue, reg, work, key):
        binding = (attempt, cli.RECEIPT_SHA256, *operator)
        fresh, (_, state, _) = store.reserve(
            reg / pilot.DB, key, cli.JOB_SHA256, permit.purpose, str(work), binding
        )
        if fresh:
            calls.append(key)
            store.bind_job(database, key, "fixture-result")
            store.finish(database, key, bundle_sha="a" * 64)
        else:
            assert state == "SEALED"
        return {"status": "COMPLETE", "job_sha256": cli.JOB_SHA256, "stdout_sha256": "b" * 64}

    monkeypatch.setattr(pilot, "run_historical", run)
    return SimpleNamespace(cli=cli, args=args, db=database, permit=permit, calls=calls)


def _command(fixture, capsys, command, *args):
    code = fixture.cli.main([command, *fixture.args, *args])
    return code, json.loads(capsys.readouterr().out.splitlines()[-1])


def _answer(monkeypatch, reply):
    def respond(prompt):
        sys.audit("builtins.input", prompt)
        return reply(prompt)

    monkeypatch.setattr("builtins.input", respond)


def test_preflight_read_only(fixture, capsys):
    code, result = _command(fixture, capsys, "preflight")
    assert code == 0 and result["status"] == "HISTORICAL_PREFLIGHT_PASSED"
    assert len(result["cases"]) == 6 and result["registry"] == "NO_PERMIT"
    assert not fixture.db.exists()


@pytest.mark.parametrize("failed_check", ["hash", "acl", "image", "receipt"])
def test_preflight_blocks_invalid_input(fixture, capsys, monkeypatch, failed_check):
    def deny(*_):
        raise ValueError("fixture denied")

    if failed_check == "hash":
        monkeypatch.setattr(pilot, "plan_sha", lambda _: "0" * 64)
    elif failed_check == "receipt":
        monkeypatch.setattr(pilot, "_verified_binding", lambda _: (None, "0" * 64, None, None))
    else:
        monkeypatch.setattr(
            fixture.cli, {"acl": "_windows_acl", "image": "_inspect_image"}[failed_check], deny
        )
    code, result = _command(fixture, capsys, "preflight")
    assert code == 2 and result["status"] == "BLOCKED"
    assert not fixture.db.exists()


def test_approve_rejects_wrong_confirmation_and_moving_hash(fixture, capsys, monkeypatch):
    _answer(monkeypatch, lambda _: "decline")
    assert _command(fixture, capsys, "approve")[0] == 2
    assert not fixture.db.exists()
    changed = fixture.permit.model_copy(update={"job_sha256": "0" * 64})
    monkeypatch.setattr(
        pilot,
        "authorization_proposal",
        lambda *_: (changed, SimpleNamespace(model_dump=lambda **_: {}), {}),
    )
    _answer(monkeypatch, lambda _: pytest.fail("Input guard must reject before reading"))
    _, result = _command(fixture, capsys, "approve")
    assert "no longer matches" in result["reason"]
    assert not fixture.db.exists()


def test_missing_permit_duplicate_approval_and_idempotent_run(fixture, capsys, monkeypatch):
    key = store.receipt_id(fixture.permit)
    assert _command(fixture, capsys, "run", "--permit-id", key)[0] == 2
    assert not fixture.db.exists()
    _answer(monkeypatch, lambda _: store.phrase(fixture.permit))
    code, result = _command(fixture, capsys, "approve")
    assert code == 0 and result["status"] == "APPROVED"
    key = result["permit_id"]
    assert _command(fixture, capsys, "approve")[0] == 2
    assert not fixture.calls
    assert _command(fixture, capsys, "run", "--permit-id", "0" * 64)[0] == 2
    assert _command(fixture, capsys, "run", "--permit-id", key)[0] == 2
    _answer(monkeypatch, lambda _: f"RUN HISTORICAL_BACKTEST_ONCE {key}")
    code, result = _command(fixture, capsys, "run", "--permit-id", key)
    assert code == 0 and result["status"] == "COMPLETE" and not result["previously_sealed"]
    assert _command(fixture, capsys, "preflight")[0] == 2
    _answer(monkeypatch, lambda _: pytest.fail("A sealed retrieval requires no new confirmation"))
    assert _command(fixture, capsys, "run", "--permit-id", key)[1]["previously_sealed"]
    assert fixture.calls == [key]


@pytest.mark.parametrize("state", ["RESERVED", "UNKNOWN"])
def test_run_blocks_uncertain_reservation(fixture, capsys, monkeypatch, state):
    store.initialize(fixture.db)
    key = store.grant(fixture.db, fixture.permit, store.phrase(fixture.permit))
    p = fixture.permit
    store.reserve(
        fixture.db,
        key,
        p.job_sha256,
        p.purpose,
        "fixture",
        (p.attempt_id, p.implementation_receipt_sha256, p.operator, p.operator_sid),
    )
    if state == "UNKNOWN":
        store.finish(fixture.db, key)
    _answer(monkeypatch, lambda _: pytest.fail("Uncertain reservation must block before input"))
    code, result = _command(fixture, capsys, "run", "--permit-id", key)
    assert code == 2 and "reconciliation" in result["reason"]
    assert fixture.calls == []


def test_rejects_altered_permit_receipt(fixture, capsys):
    store.initialize(fixture.db)
    with store.transaction(fixture.db) as conn:
        conn.execute(
            "INSERT INTO permits VALUES (?, ?, ?, ?)",
            ("0" * 64, fixture.permit.scope, fixture.permit.model_dump_json(), "altered"),
        )
    code, result = _command(fixture, capsys, "preflight")
    assert code == 2 and "altered" in result["reason"]


def test_image_inspection_has_no_run_or_pull(fixture, tmp_path, monkeypatch):
    def execute(command, **kwargs):
        assert command[5:] == ["image", "inspect", "fixture"]
        assert "DOCKER_HOST" not in kwargs["env"]
        metadata = [{"Id": "fixture", "Os": "linux", "Config": {"Volumes": None}}]
        return subprocess.CompletedProcess(command, 0, json.dumps(metadata))

    monkeypatch.setenv("DOCKER_HOST", "fixture")
    monkeypatch.setattr(subprocess, "run", execute)
    fixture.cli._inspect_image(
        SimpleNamespace(docker=Path("docker.exe"), image="fixture"), tmp_path
    )
    assert list(tmp_path.glob(".historical-inspect-config")) == []


@pytest.mark.skipif(
    os.environ.get("TRADING_LAB_55B_DOCKER") != "1", reason="Explicit Windows Docker acceptance"
)
def test_native_cli_image_inspection_and_read_only_registry(tmp_path, cli_module):
    cli = cli_module
    registry = tmp_path / "registry"
    scratch = tmp_path / "scratch"
    registry.mkdir()
    scratch.mkdir()
    case = "synthetic:" + "a" * 64
    with (
        cli.ntfs.pinned_root(registry, existing=True),
        cli.ntfs.pinned_root(scratch, existing=True),
    ):
        cli._inspect_image(pilot.HistoricalVerifier(), scratch)
        assert not list(scratch.iterdir())
        assert cli._registry(registry / pilot.DB, case) == (None, None)
        assert not list(registry.iterdir())
        database = registry / pilot.DB
        store.initialize(database)
        before = database.read_bytes()
        assert cli._registry(database, case) == (None, None)
        assert database.read_bytes() == before
        assert list(registry.iterdir()) == [database]


@pytest.mark.skipif(
    os.environ.get("TRADING_LAB_55B_DOCKER") != "1", reason="Explicit Windows Docker acceptance"
)
def test_native_cli_checks_acl_and_effective_access(tmp_path, cli_module):
    cli = cli_module
    registry = tmp_path / "registry"
    scratch = tmp_path / "scratch"
    _, sid = pilot.current_operator()
    icacls = Path(os.environ["SystemRoot"]) / "System32/icacls.exe"
    for root in (registry, scratch):
        root.mkdir()
        subprocess.run(
            [str(icacls), str(root), "/grant:r", f"*{sid}:(OI)(CI)(F)", "/inheritance:r"],
            check=True,
            capture_output=True,
        )
    with (
        cli.ntfs.pinned_root(registry, existing=True),
        cli.ntfs.pinned_root(scratch, existing=True),
    ):
        cli._windows_acl(registry, scratch, sid)
        subprocess.run(
            [str(icacls), str(scratch), "/grant", "*S-1-5-32-545:(RX)"],
            check=True,
            capture_output=True,
        )
        with pytest.raises(cli.Blocked, match="ACL"):
            cli._windows_acl(registry, scratch, sid)
