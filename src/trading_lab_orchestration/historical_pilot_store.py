"""A separate, single-use historical permit and reservation journal."""

import ctypes
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import ExitStack, closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from . import study_storage_windows as ntfs
from .contracts import Model, canonical
from .historical_pilot_contract import hash_bytes
from .isolated_study_contract import BASE, Hash
from .pilot_authorization import current_operator

APP_ID = 0x544C3535
DB = "historical-pilot.sqlite3"
HISTORICAL = "HISTORICAL_BACKTEST_ONCE"
ISSUE_SCOPE = "issue-3"
ANCHOR = ".historical-pilot-issue-3.json"
LOCK = ".historical-pilot-issue-3.lock"
SCHEMA = """
PRAGMA application_id=1414280501;
PRAGMA user_version=1;
CREATE TABLE permits (
    id TEXT PRIMARY KEY, scope TEXT UNIQUE NOT NULL, receipt TEXT NOT NULL,
    confirmation TEXT NOT NULL
);
CREATE TABLE runs (
    permit TEXT PRIMARY KEY REFERENCES permits(id),
    scratch TEXT NOT NULL,
    job TEXT,
    state TEXT NOT NULL CHECK(state IN ('RESERVED','SEALED','UNKNOWN')),
    bundle_sha TEXT,
    CHECK(
        (state='RESERVED' AND bundle_sha IS NULL)
        OR (state='SEALED' AND bundle_sha IS NOT NULL AND job IS NOT NULL)
        OR (state='UNKNOWN' AND bundle_sha IS NULL)
    )
);
CREATE TRIGGER no_replace_permit BEFORE INSERT ON permits
WHEN EXISTS(SELECT 1 FROM permits WHERE id=NEW.id OR scope=NEW.scope)
BEGIN SELECT RAISE(ABORT, 'historical permit already exists'); END;
CREATE TRIGGER no_replace_run BEFORE INSERT ON runs
WHEN EXISTS(SELECT 1 FROM runs WHERE permit=NEW.permit)
BEGIN SELECT RAISE(ABORT, 'historical reservation already exists'); END;
CREATE TRIGGER no_permit_update BEFORE UPDATE ON permits
BEGIN SELECT RAISE(ABORT, 'immutable historical permit'); END;
CREATE TRIGGER no_permit_delete BEFORE DELETE ON permits
BEGIN SELECT RAISE(ABORT, 'immutable historical permit'); END;
CREATE TRIGGER enforce_initial_run BEFORE INSERT ON runs
WHEN NEW.state!='RESERVED' OR NEW.job IS NOT NULL OR NEW.bundle_sha IS NOT NULL
    OR NOT EXISTS(SELECT 1 FROM permits WHERE id=NEW.permit)
BEGIN SELECT RAISE(ABORT, 'historical run requires an initial reservation'); END;
CREATE TRIGGER no_run_delete BEFORE DELETE ON runs
BEGIN SELECT RAISE(ABORT, 'historical reservation is consumed'); END;
CREATE TRIGGER enforce_run_transition BEFORE UPDATE ON runs
WHEN OLD.state!='RESERVED' OR NEW.permit!=OLD.permit OR NEW.scratch!=OLD.scratch
    OR (OLD.job IS NOT NULL AND NEW.job IS NOT OLD.job)
    OR (NEW.state='RESERVED' AND (OLD.job IS NOT NULL OR NEW.job IS NULL))
BEGIN SELECT RAISE(ABORT, 'invalid historical reservation transition'); END;
"""


class Permit(Model):
    schema_version: Literal["1.0"] = "1.0"
    purpose: Literal["HISTORICAL_BACKTEST_ONCE", "SYNTHETIC_BACKTEST_ONCE"]
    issue_number: Literal[3] = 3
    pilot_commit: Literal[BASE] = BASE
    attempt_id: Annotated[str, Field(pattern=r"^attempt_[a-f0-9]{32}$")]
    implementation_receipt_sha256: Hash
    job_sha256: Hash
    operator: Annotated[str, Field(min_length=1, max_length=120)]
    operator_sid: Annotated[str, Field(pattern=r"^S-1-(?:[0-9]+-)*[0-9]+$")]
    approved_at: datetime

    @model_validator(mode="after")
    def validate_time(self):
        if self.approved_at.utcoffset() != UTC.utcoffset(None) or self.approved_at > datetime.now(
            UTC
        ):
            raise ValueError("Approval timestamp is not past UTC")
        return self

    @property
    def scope(self):
        if self.purpose == HISTORICAL:
            return ISSUE_SCOPE
        return f"synthetic:{self.job_sha256}"


def phrase(permit):
    return f"AUTHORIZE {permit.purpose} {permit.attempt_id} {permit.job_sha256}"


def receipt_id(permit):
    return hash_bytes(canonical(permit.model_dump(mode="json")).encode())


def designated_registry():
    local = ctypes.create_unicode_buffer(260)
    if os.name != "nt" or ctypes.windll.shell32.SHGetFolderPathW(None, 0x001C, None, 0, local):
        raise ValueError("Windows LocalAppData folder is unavailable")
    if not local.value:
        raise ValueError("Windows LocalAppData folder is unavailable")
    return Path(local.value) / "TradingLab/HistoricalPilot55B"


def check_acl(path, sid, *, directory=True, private=False):
    script = """
    $ErrorActionPreference = 'Stop'
    $file = $env:TL55B_ACL_PATH
    if ($env:TL55B_ACL_DIRECTORY -eq '1') { $acl = [IO.Directory]::GetAccessControl($file) }
    else { $acl = [IO.File]::GetAccessControl($file) }
    $type = [Security.Principal.SecurityIdentifier]
    if ($acl.GetOwner($type).Value -ne $env:TL55B_OPERATOR_SID) { throw 'Owner mismatch' }
    $trusted = @($env:TL55B_OPERATOR_SID, 'S-1-5-18', 'S-1-5-32-544', 'S-1-3-4')
    foreach ($rule in $acl.GetAccessRules($true, $true, $type)) {
        $allow = $rule.AccessControlType -eq 'Allow'
        $mutation = ([int]$rule.FileSystemRights -band 0x500D0156) -ne 0
        if ($allow -and ($mutation -or $env:TL55B_ACL_PRIVATE -eq '1') -and
            $rule.IdentityReference.Value -notin $trusted) {
            throw 'Unexpected allow entry'
        }
    }
    """
    env = dict(
        os.environ,
        TL55B_ACL_PATH=str(path),
        TL55B_ACL_DIRECTORY="1" if directory else "0",
        TL55B_ACL_PRIVATE="1" if private else "0",
        TL55B_OPERATOR_SID=sid,
    )
    system = ctypes.create_unicode_buffer(32768)
    count = ctypes.windll.kernel32.GetSystemDirectoryW(system, len(system))
    if not 0 < count < len(system):
        raise ValueError("Windows system directory is unavailable")
    powershell = Path(system.value) / "WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
        env=env,
        capture_output=True,
        timeout=15,
    )
    if result.returncode:
        raise ValueError("Historical storage owner/ACL verification failed")
    if directory:
        # READ_CONTROL | READ_ATTRIBUTES | ADD_FILE | ADD_SUBDIRECTORY.
        handle = ntfs._open_no_reparse(
            path, 0x20086, ntfs.SHARE_READ | ntfs.SHARE_WRITE, 1, is_directory=True
        )
        try:
            ntfs._info(handle, directory=True)
        finally:
            ntfs.close_handle(handle)


@contextmanager
def _file(path, share):
    handle = ntfs._open_no_reparse(path, ntfs.READ, share, 1)
    try:
        yield ntfs._info(handle)
    finally:
        ntfs.close_handle(handle)


def _file_identity(path):
    with _file(path, ntfs.SHARE_READ | ntfs.SHARE_WRITE) as info:
        return [info.volume, (info.index_high << 32) | info.index_low]


def _reject_sidecars(path):
    prefix = path.name.casefold() + "-"
    if any(entry.name.casefold().startswith(prefix) for entry in path.parent.iterdir()):
        raise ValueError("SQLite sidecar requires manual reconciliation")


def _check_rollback_header(path):
    with path.open("rb") as raw:
        header = raw.read(100)
    if not header.startswith(b"SQLite format 3\0") or header[18:20] != b"\x01\x01":
        raise ValueError("Expected a clean rollback journal SQLite database")


@contextmanager
def rollback_snapshot(path):
    """Pin every parent and exclude writers while opening a clean rollback database."""
    with ntfs.pinned_root(path.parent, existing=True) as root:
        file = root / path.name
        _reject_sidecars(file)
        with _file(file, ntfs.SHARE_READ):
            _reject_sidecars(file)
            _check_rollback_header(file)
            # The kernel denies write/delete through this handle. No journal may
            # exist, so immutable cannot hide a live WAL or incomplete commit.
            with closing(sqlite3.connect(file.as_uri() + "?mode=ro&immutable=1", uri=True)) as conn:
                conn.execute("PRAGMA query_only=ON")
                yield conn
                _reject_sidecars(file)


@contextmanager
def operator_registry(path, operator):
    if path.name != DB or path.parent != designated_registry():
        raise ValueError("Use the canonical Issue #3 historical registry")
    if operator != current_operator():
        raise ValueError("Historical Windows operator changed")
    with ntfs.pinned_root(path.parent, existing=True) as root:
        check_acl(root.parent, operator[1])
        check_acl(root, operator[1])
        yield root


def _anchor(root, *, create=False):
    db = root / DB
    anchor = root.parent / ANCHOR
    _reject_sidecars(db)
    if not os.path.lexists(anchor):
        if not os.path.lexists(db) and not create:
            return
        if not create:
            raise ValueError("Canonical registry has no identity seal")
        payload = {"root": ntfs.directory_identity(root), "db": _file_identity(db)}
        ntfs.publish(anchor, canonical(payload).encode(), 4096)
        return
    check_acl(anchor, current_operator()[1], directory=False)
    expected = json.loads(ntfs.read(anchor, 4096))
    if not os.path.lexists(db) or expected != {
        "root": ntfs.directory_identity(root),
        "db": _file_identity(db),
    }:
        raise ValueError("Canonical registry identity changed; reconcile manually")


def _confirm(phrase, action):
    if os.name != "nt" or not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ValueError("Interactive Windows historical confirmation required")
    if input(f"Type {phrase} to {action}: ") != phrase:
        raise ValueError("Explicit historical confirmation did not match")


def _check_schema(conn):
    if (
        conn.execute("PRAGMA application_id").fetchone()[0] != APP_ID
        or conn.execute("PRAGMA user_version").fetchone()[0] != 1
    ):
        raise ValueError("Unrecognized historical authorization database")


@contextmanager
def transaction(path):
    if path.name != DB:
        raise ValueError("A dedicated historical-pilot.sqlite3 is required")
    conn = sqlite3.connect(path.absolute().as_uri() + "?mode=rw", uri=True, timeout=5)
    try:
        _check_schema(conn)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("BEGIN IMMEDIATE")
        with conn:
            yield conn
    finally:
        conn.close()


def initialize(path):
    if path.name != "historical-pilot.sqlite3":
        raise ValueError("A dedicated historical-pilot.sqlite3 is required")
    with path.open("xb"):
        pass
    conn = sqlite3.connect(path)
    try:
        conn.executescript("BEGIN IMMEDIATE;" + SCHEMA + "COMMIT;")
    finally:
        conn.close()


def grant(path, permit, confirmation=None):
    with ExitStack() as stack:
        if permit.purpose == HISTORICAL:
            if confirmation is not None:
                raise ValueError("Historical confirmation must be entered interactively")
            operator = permit.operator, permit.operator_sid
            root = stack.enter_context(operator_registry(path, operator))
            check_acl(root, operator[1], private=True)
            stack.enter_context(ntfs.exclusive_lock(root.parent / LOCK))
            _anchor(root)
            if permit_status(path, permit.scope)[0]:
                raise ValueError("A historical permit already exists")
            confirmation = phrase(permit)
            _confirm(confirmation, "authorize these six cases")
            if current_operator() != operator:
                raise ValueError("Historical Windows operator changed after confirmation")
            if not os.path.lexists(path):
                initialize(path)
                _anchor(root, create=True)
            stack.enter_context(guard_registry_file(root, operator[1]))
            permit = permit.model_copy(update={"approved_at": datetime.now(UTC)})
        if confirmation != phrase(permit):
            raise ValueError("Explicit historical confirmation did not match")
        key = receipt_id(permit)
        with transaction(path) as conn:
            conn.execute(
                "INSERT INTO permits VALUES (?, ?, ?, ?)",
                (key, permit.scope, canonical(permit.model_dump(mode="json")), confirmation),
            )
        return key


@contextmanager
def guard_registry_file(root, sid):
    path = root / DB
    with _file(path, ntfs.SHARE_READ | ntfs.SHARE_WRITE):
        _anchor(root)
        _check_rollback_header(path)
        check_acl(path, sid, directory=False, private=True)
        yield


def reserve(path, permit_id, job_sha256, purpose, scratch, binding=None):
    with ExitStack() as stack:
        if purpose == HISTORICAL:
            if binding is None:
                raise ValueError("Verified pilot and Windows operator required")
            root = stack.enter_context(operator_registry(path, binding[2:]))
            stack.enter_context(guard_registry_file(root, binding[3]))
        with transaction(path) as conn:
            row = conn.execute(
                "SELECT receipt,confirmation,scope FROM permits WHERE id=?", (permit_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Explicit historical permit required")
            permit = Permit.model_validate_json(row[0])
            if (row[1], row[2]) != (phrase(permit), permit.scope) or (
                receipt_id(permit),
                permit.job_sha256,
                permit.purpose,
            ) != (
                permit_id,
                job_sha256,
                purpose,
            ):
                raise ValueError("Permit integrity or sealed execution scope mismatch")
            if purpose == "HISTORICAL_BACKTEST_ONCE" and binding != (
                permit.attempt_id,
                permit.implementation_receipt_sha256,
                permit.operator,
                permit.operator_sid,
            ):
                raise ValueError(
                    "Historical permit does not match the verified pilot and Windows operator"
                )
            run = conn.execute(
                "SELECT scratch,job,state,bundle_sha FROM runs WHERE permit=?", (permit_id,)
            ).fetchone()
            if run is None:
                if purpose == HISTORICAL:
                    _confirm(
                        f"RUN {HISTORICAL} {permit_id}", "consume the permit and start the lot"
                    )
                    if current_operator() != binding[2:]:
                        raise ValueError("Historical Windows operator changed after confirmation")
                conn.execute(
                    "INSERT INTO runs(permit,scratch,state) VALUES (?,?,'RESERVED')",
                    (permit_id, scratch),
                )
                return True, (None, "RESERVED", None)
            if run[0] != scratch:
                raise ValueError("The consumed reservation belongs to a different scratch identity")
            return False, run[1:]


def bind_job(path, permit_id, identity):
    with transaction(path) as conn:
        cursor = conn.execute(
            "UPDATE runs SET job=? WHERE permit=? AND state='RESERVED' AND job IS NULL",
            (identity, permit_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Historical reservation is not bindable")


def finish(path, permit_id, *, bundle_sha=None):
    state = "SEALED" if bundle_sha is not None else "UNKNOWN"
    with transaction(path) as conn:
        cursor = conn.execute(
            "UPDATE runs SET state=?,bundle_sha=? WHERE permit=? AND state='RESERVED'",
            (state, bundle_sha, permit_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Historical reservation is already terminal or uncertain")


def synthetic_key(path, scope):
    with transaction(path) as conn:
        row = conn.execute("SELECT id,scope FROM permits").fetchall()
        if len(row) != 1 or row[0][1] != scope:
            raise ValueError("Use the same isolated synthetic registry for replay")
        return row[0][0]


def permit_status(path, scope):
    """Read the sealed receipt and reservation in a single immutable snapshot."""
    if path.name != DB or not path.parent.is_dir():
        raise ValueError("A pre-provisioned historical registry directory is required")
    _reject_sidecars(path)
    if not os.path.lexists(path):
        return None, None
    with rollback_snapshot(path) as conn:
        _check_schema(conn)
        row = conn.execute(
            """SELECT p.id, p.receipt, p.confirmation, r.state
               FROM permits p LEFT JOIN runs r ON r.permit=p.id WHERE p.scope=?""",
            (scope,),
        ).fetchone()
    if row is None:
        return None, None
    key, raw, confirmation, state = row
    permit = Permit.model_validate_json(raw)
    if permit.scope != scope or key != receipt_id(permit) or confirmation != phrase(permit):
        raise ValueError("Stored historical permit receipt or confirmation was altered")
    return (key, permit), state


def historical_status(path, scope, operator):
    with operator_registry(path, operator) as root:
        _anchor(root)
        if os.path.lexists(path):
            with _file(path, ntfs.SHARE_READ):
                _anchor(root)
                check_acl(path, operator[1], directory=False, private=True)
                return permit_status(path, scope)
        return None, None


def assert_unconsumed(path, scope, *, operator=None):
    if scope == ISSUE_SCOPE:
        if operator is None:
            raise ValueError("Verified Windows operator required")
        _, state = historical_status(path, scope, operator)
    else:
        _, state = permit_status(path, scope)
    if state is not None:
        raise ValueError("The designated historical permit was already consumed")
