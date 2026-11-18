import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from trading_lab_orchestration import historical_pilot as pilot
from trading_lab_orchestration import historical_pilot_store as store
from trading_lab_orchestration.readonly import APPLICATION_ID, SCHEMA_VERSION


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
        mode="HISTORICAL",
        plan=SimpleNamespace(
            job_id="fixture",
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
    monkeypatch.setattr(cli, "_inspect_image", lambda *_: None)
    terminal = SimpleNamespace(isatty=lambda: True)
    monkeypatch.setattr(store, "sys", SimpleNamespace(stdin=terminal, stdout=terminal))
    monkeypatch.setattr(store, "designated_registry", lambda: registry)
    monkeypatch.setattr(store, "current_operator", lambda: operator)
    monkeypatch.setattr(store, "check_acl", lambda *_, **__: None)
    monkeypatch.setattr(cli.ntfs, "pinned_root", lambda root, **_: nullcontext(root))
    monkeypatch.setattr(cli.ntfs, "exclusive_lock", lambda _: nullcontext())
    monkeypatch.setattr(store, "_file", lambda path, _: nullcontext(path.stat()))
    monkeypatch.setattr(store, "_file_identity", lambda path: [path.stat().st_ino])
    monkeypatch.setattr(cli.ntfs, "directory_identity", lambda path: [path.stat().st_ino])
    monkeypatch.setattr(cli.ntfs, "read", lambda path, _: path.read_bytes())
    monkeypatch.setattr(cli.ntfs, "publish", lambda path, raw, _: path.write_bytes(raw))

    def directory(path, *, fresh=False, **_):
        if fresh:
            path.mkdir()
        return nullcontext()

    monkeypatch.setattr(cli.ntfs, "directory", directory)
    monkeypatch.setattr(pilot, "_paths", lambda *_: None)
    monkeypatch.setattr(pilot, "HistoricalVerifier", lambda: SimpleNamespace(image="fixture"))
    monkeypatch.setattr(
        pilot,
        "prepare",
        lambda *_, **__: (
            job,
            {pilot.CANDLES: b"fixture"},
            {"parquet_sha256": "p", "manifest_sha256": "m"},
        ),
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
        approved_at=datetime.now(UTC),
    )

    def execute(*_):
        calls.append("fixture")
        return {"status": "COMPLETE", "job_sha256": cli.JOB_SHA256, "stdout_sha256": "b" * 64}

    monkeypatch.setattr(pilot, "_execute", execute)
    monkeypatch.setattr(
        pilot, "_read_complete", lambda path, *_: json.loads((path / pilot.RESULT).read_bytes())
    )
    return SimpleNamespace(
        cli=cli,
        args=args,
        db=database,
        permit=permit,
        calls=calls,
        registry=registry,
        scratch=scratch,
    )


def _command(fixture, capsys, command, *args):
    code = fixture.cli.main([command, *fixture.args, *args])
    return code, json.loads(capsys.readouterr().out.splitlines()[-1])


def _answer(monkeypatch, reply):
    def respond(prompt):
        return reply(prompt)

    monkeypatch.setattr("builtins.input", respond)


def test_preflight_read_only(fixture, capsys):
    code, result = _command(fixture, capsys, "preflight")
    assert code == 0 and result["status"] == "HISTORICAL_PREFLIGHT_PASSED"
    assert len(result["cases"]) == 6 and result["registry"] == "NO_PERMIT"
    assert not fixture.db.exists()


def _inventory(folder):
    return {path.name: pilot.hash_bytes(path.read_bytes()) for path in folder.iterdir()}


@pytest.mark.parametrize("coordinator", [True, False], ids=["coordinator", "registry"])
@pytest.mark.parametrize("journal", ["wal-header", "wal", "journal", "shm", "mj-fixture", "clean"])
def test_sqlite_inspection_never_changes_directory(fixture, tmp_path, coordinator, journal):
    folder = tmp_path / "snapshot"
    folder.mkdir()
    db = folder / ("queue.sqlite3" if coordinator else store.DB)
    if coordinator:
        with sqlite3.connect(db) as connection:
            connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.execute("CREATE TABLE fixture(id INTEGER)")
        connection.close()
    else:
        store.initialize(db)
    if journal in {"wal", "wal-header"}:
        live = tmp_path / "live.sqlite3"
        shutil.copyfile(db, live)
        with sqlite3.connect(live) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("CREATE TABLE committed_in_wal(id INTEGER)")
            writer.commit()
            shutil.copyfile(live, db)
            if journal == "wal":
                shutil.copyfile(str(live) + "-wal", str(db) + "-wal")
        writer.close()
    elif journal in {"journal", "shm", "mj-fixture"}:
        db.with_name(db.name + "-" + journal).write_bytes(b"uncertain")

    def inspect():
        if coordinator:
            with pilot._HistoricalCoordinator(db).snapshot():
                pass
        else:
            store.assert_unconsumed(db, "synthetic:fixture")

    before = _inventory(folder)
    if journal == "clean":
        inspect()
    else:
        with pytest.raises(ValueError, match="SQLite sidecar|clean rollback"):
            inspect()
    assert _inventory(folder) == before


@pytest.mark.parametrize("failed_check", ["hash", "acl", "image", "receipt"])
def test_preflight_blocks_invalid_input(fixture, capsys, monkeypatch, failed_check):
    def deny(*_, **__):
        raise ValueError("fixture denied")

    if failed_check == "hash":
        monkeypatch.setattr(pilot, "plan_sha", lambda _: "0" * 64)
    elif failed_check == "receipt":
        monkeypatch.setattr(pilot, "_verified_binding", lambda _: (None, "0" * 64, None, None))
    elif failed_check == "acl":
        monkeypatch.setattr(store, "check_acl", deny)
    else:
        monkeypatch.setattr(fixture.cli, "_inspect_image", deny)
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
    assert result["status"] == "BLOCKED"
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
    before = _inventory(fixture.registry)
    assert _command(fixture, capsys, "run", "--permit-id", key)[1]["previously_sealed"]
    assert _inventory(fixture.registry) == before
    assert fixture.calls == ["fixture"]


def test_direct_python_cannot_use_another_registry_or_skip_confirmation(
    fixture, tmp_path, monkeypatch
):
    other = tmp_path / "alternate"
    other.mkdir()
    binding = fixture.permit.operator, fixture.permit.operator_sid
    _answer(monkeypatch, lambda _: pytest.fail("Alternate registry must block before input"))
    with pytest.raises(ValueError, match="canonical"):
        store.grant(other / store.DB, fixture.permit)
    with pytest.raises(ValueError, match="canonical"):
        pilot.authorization_proposal(tmp_path, tmp_path, other)

    _answer(monkeypatch, lambda _: store.phrase(fixture.permit))
    key = store.grant(fixture.db, fixture.permit)
    second = fixture.permit.model_copy(update={"attempt_id": "attempt_" + "2" * 32})
    with pytest.raises(ValueError, match="already exists"):
        store.grant(fixture.db, second)
    terminal = SimpleNamespace(isatty=lambda: False)
    monkeypatch.setattr(store, "sys", SimpleNamespace(stdin=terminal, stdout=terminal))
    with pytest.raises(ValueError, match="canonical"):
        pilot.run_historical(tmp_path, tmp_path, other, fixture.scratch, key)
    with pytest.raises(ValueError, match="Interactive"):
        pilot.run_historical(
            tmp_path / "data", tmp_path / "queue" / "db", fixture.registry, fixture.scratch, key
        )
    _, state = store.historical_status(fixture.db, fixture.permit.scope, binding)
    assert state is None and fixture.calls == [] and list(other.iterdir()) == []


def test_direct_concurrent_reservation_prompts_once(fixture, monkeypatch):
    _answer(monkeypatch, lambda _: store.phrase(fixture.permit))
    key = store.grant(fixture.db, fixture.permit)
    permit = fixture.permit
    binding = (
        permit.attempt_id,
        permit.implementation_receipt_sha256,
        permit.operator,
        permit.operator_sid,
    )
    inputs = []

    def confirm(phrase, action):
        inputs.append((phrase, action))

    monkeypatch.setattr(store, "_confirm", confirm)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(
            workers.map(
                lambda _: store.reserve(
                    fixture.db, key, permit.job_sha256, permit.purpose, "scratch", binding
                ),
                range(2),
            )
        )
    assert sorted(fresh for fresh, _ in results) == [False, True]
    assert len(inputs) == 1


def test_direct_reservation_rejects_wal_header_without_creating_sidecars(fixture, monkeypatch):
    _answer(monkeypatch, lambda _: store.phrase(fixture.permit))
    key = store.grant(fixture.db, fixture.permit)
    raw = bytearray(fixture.db.read_bytes())
    raw[18:20] = b"\x02\x02"
    fixture.db.write_bytes(raw)
    before = _inventory(fixture.registry)
    _answer(monkeypatch, lambda _: pytest.fail("An uncertain registry must block before input"))
    with pytest.raises(ValueError, match="clean rollback"):
        pilot.run_historical(
            fixture.registry.parent / "data",
            fixture.registry.parent / "queue" / "db",
            fixture.registry,
            fixture.scratch,
            key,
        )
    assert _inventory(fixture.registry) == before and fixture.calls == []


@pytest.mark.parametrize("target", ["registry", "database"])
def test_identity_seal_blocks_replacement(fixture, monkeypatch, target):
    _answer(monkeypatch, lambda _: store.phrase(fixture.permit))
    store.grant(fixture.db, fixture.permit)
    if target == "registry":
        old = fixture.registry.with_name("old")
        fixture.registry.rename(old)
        fixture.registry.mkdir()
        shutil.copyfile(old / store.DB, fixture.db)
    else:
        old = fixture.db.with_name("old.sqlite3")
        fixture.db.rename(old)
        shutil.copyfile(old, fixture.db)
    with pytest.raises(ValueError, match="identity changed"):
        store.historical_status(
            fixture.db, fixture.permit.scope, (fixture.permit.operator, fixture.permit.operator_sid)
        )


@pytest.mark.parametrize("state", ["RESERVED", "UNKNOWN"])
def test_run_blocks_uncertain_reservation(fixture, capsys, monkeypatch, state):
    _answer(monkeypatch, lambda _: store.phrase(fixture.permit))
    key = _command(fixture, capsys, "approve")[1]["permit_id"]
    _answer(monkeypatch, lambda _: f"RUN HISTORICAL_BACKTEST_ONCE {key}")
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
    store._anchor(fixture.registry, create=True)
    with store.transaction(fixture.db) as conn:
        conn.execute(
            "INSERT INTO permits VALUES (?, ?, ?, ?)",
            ("0" * 64, fixture.permit.scope, fixture.permit.model_dump_json(), "altered"),
        )
    code, result = _command(fixture, capsys, "preflight")
    assert code == 2 and result["status"] == "BLOCKED"


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
        assert store.permit_status(registry / pilot.DB, case) == (None, None)
        assert not list(registry.iterdir())
        database = registry / pilot.DB
        store.initialize(database)
        before = database.read_bytes()
        assert store.permit_status(database, case) == (None, None)
        with store.rollback_snapshot(database) as reader:
            assert reader.execute("SELECT COUNT(*) FROM permits").fetchone()[0] == 0
            with pytest.raises(sqlite3.Error):
                writer = sqlite3.connect(database.as_uri() + "?mode=rw", uri=True, timeout=0)
                try:
                    writer.execute("BEGIN IMMEDIATE")
                    writer.execute("CREATE TABLE unexpected_write(id INTEGER)")
                finally:
                    writer.close()
        assert database.read_bytes() == before
        assert list(registry.iterdir()) == [database]
        alias = registry / "hard-link.sqlite3"
        os.link(database, alias)
        with pytest.raises(ValueError, match="links"):
            store.permit_status(database, case)
        alias.unlink()
        assert database.read_bytes() == before


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
        store.check_acl(scratch, sid, private=True)
        subprocess.run(
            [str(icacls), str(scratch), "/grant", "*S-1-5-32-545:(RX)"],
            check=True,
            capture_output=True,
        )
        store.check_acl(scratch, sid)
        with pytest.raises(ValueError, match="ACL"):
            store.check_acl(scratch, sid, private=True)
