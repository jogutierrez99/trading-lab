"""One explicitly authorized pilot compatibility repair; never invokes a model."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal
from uuid import uuid4

from .contracts import Identifier, Model, Text, canonical, digest
from .implementation import Coordinator
from .implementation_contracts import Hash, ImplementationRequest
from .process_identity import inspected, pending, record_process
from .processes import coordinator_lock, run_process
from .store import utc_now
from .workspaces import file_hash, inventory, write_json

OPERATION = "PILOT_UTC_INDEX_COMPATIBILITY_V1"
PATCH_SHA256 = "e331bdbcc3e97e81b6d648dc37bb6f4f329b920fa7a9d2ce05215952550d0bc5"
SOURCE_FILES = {
    "src/quant_lab/strategies/manual_engulfing_breakout_v1.py": (
        "8f61601832fbf010eaea294bb905d02d5c2718a5ebac4c4c3dfb2537db1249e1"
    ),
    "configs/strategies/manual_engulfing_breakout_v1.yaml": (
        "313317a88d41c2116d15902df606fec78cc15f45ccb793442bee599e0934b4af"
    ),
    "tests/unit/test_manual_engulfing_breakout_v1.py": (
        "e190633a866666eff9a268936e387b19cb2e23b0cee1d80d9e123b4bb5bfe159"
    ),
}
TARGET_FILES = dict(
    zip(
        SOURCE_FILES,
        (
            "5fc38dca9ac91deac7852cb3a47d2edf3cbbb181439655278d7395f68787aecc",
            "38322ffd84b1cf4d476e01566edfaa8b8211a9cf8ef372be5635de0894a42427",
            "0e5da17dc63e52f82db41ecf25b7a0432202a11cfe4f8367b0d154e5ea631168",
        ),
        strict=True,
    )
)


class ManualRepairRequest(Model):
    schema_version: Literal["1.0"]
    kind: Literal["ManualTechnicalRepairRequest"]
    repair_id: Identifier
    source_attempt_id: Identifier
    task_id: Identifier
    candidate_id: Identifier
    operation: Literal["PILOT_UTC_INDEX_COMPATIBILITY_V1"]
    author: Text
    authorization: Text
    source_receipt_sha256: Hash
    patch_sha256: Hash
    base_commit: Text
    source_files: dict[Text, Hash]
    target_version: Literal["1.0.1"]
    version_amendment: Text
    model_calls_permitted: Literal[0]


class ManualRepair:
    def __init__(self, store):
        self.store = store
        self.lock = store.path.with_suffix(".implementation.lock")

    def get(self, identifier):
        with self.store.connection() as conn:
            row = conn.execute(
                "SELECT * FROM manual_repairs WHERE repair_id=?", (identifier,)
            ).fetchone()
        if not row:
            raise ValueError("Unknown manual repair identity")
        return inspected(row)

    def _event(self, conn, row, state, reason):
        task = conn.execute("SELECT * FROM tasks WHERE task_id=?", (row["task_id"],)).fetchone()
        self.store._event(
            conn,
            task["candidate_id"],
            row["task_id"],
            "task",
            task["status"],
            task["status"],
            reason,
            {"manual_repair_id": row["repair_id"], "repair_status": state},
            actor="authorized_manual_technical_repair",
        )

    def _state(self, identifier, state, reason):
        with self.store.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM manual_repairs WHERE repair_id=?", (identifier,)
            ).fetchone()
            conn.execute(
                "UPDATE manual_repairs SET status=?,error=?,ended_at_utc=? WHERE repair_id=?",
                (state, reason, None if state == "UNKNOWN" else utc_now(), identifier),
            )
            self._event(conn, row, state, reason)
        return self.get(identifier)

    def _pid(self, identifier, pid):
        with self.store.transaction() as conn:
            record_process(conn, "manual_repairs", "repair_id", identifier, pid)

    def inspect(self, identifier):
        row = self.get(identifier)
        if row["status"] == "RUNNING":
            try:
                with coordinator_lock(self.lock):
                    if self.get(identifier)["status"] == "RUNNING":
                        row = self._state(identifier, "UNKNOWN", "Manual repair owner disappeared")
            except ValueError:
                pass
        return row

    @staticmethod
    def _seal(root):
        return digest(
            canonical(
                {
                    name: file_hash(root / name)
                    for name in (
                        "baseline.json",
                        "before-tree.json",
                        "repair.patch",
                        "native-request.json",
                    )
                }
            )
        )

    def apply(self, source_id, patch, artifacts, author, authorization):
        from .execution_inputs import archive_base, relative_file, verified_implementation

        if not author.strip() or not authorization.strip() or file_hash(patch) != PATCH_SHA256:
            raise ValueError(
                "Explicit author/authorization and the exact reviewed patch are required"
            )
        with coordinator_lock(self.lock):
            source, original_request, source_receipt_path, source_receipt = verified_implementation(
                self.store, source_id
            )
            if (
                source_receipt["files"] != SOURCE_FILES
                or original_request.plan.target != "manual_engulfing_breakout_v1"
            ):
                raise ValueError("This route only repairs the exact reviewed pilot1.0.0 delivery")
            identifier = "repair_" + uuid4().hex
            root = Path(artifacts).resolve() / identifier
            for protected in (Path(source["repo"]), Path(source["root"])):
                if root.is_relative_to(protected.resolve()) or protected.resolve().is_relative_to(
                    root
                ):
                    raise ValueError("Use a separate manual repair artifact directory")
            with self.store.transaction() as conn:
                numbers = [
                    row[0]
                    for row in conn.execute(
                        "SELECT number FROM attempts WHERE task_id=? ORDER BY number",
                        (source["task_id"],),
                    )
                ]
                if numbers != [1, 2, 3] or source["number"] != 3:
                    raise ValueError(
                        "Pilot manual exception requires the audited exhausted3/3 budget"
                    )
                if any(
                    conn.execute(
                        f"SELECT 1 FROM {table} WHERE status IN ('PREPARED','RUNNING','UNKNOWN')"
                    ).fetchone()
                    for table in ("attempts", "executions", "manual_repairs")
                ):
                    raise ValueError("A job is active or uncertain; reconcile before manual repair")
                if conn.execute(
                    "SELECT 1 FROM manual_repairs WHERE source_attempt_id=?", (source_id,)
                ).fetchone():
                    raise ValueError(
                        "This source already has its one manual repair; no retry/reset"
                    )
                conn.execute(
                    """INSERT INTO manual_repairs(repair_id,task_id,source_attempt_id,operation,
                    status,root,created_at_utc) VALUES (?,?,?,?,'RUNNING',?,?)""",
                    (identifier, source["task_id"], source_id, OPERATION, str(root), utc_now()),
                )
                self._event(
                    conn,
                    {"task_id": source["task_id"], "repair_id": identifier},
                    "RUNNING",
                    authorization,
                )
            try:
                root.mkdir(parents=True, exist_ok=False)
                workspace = root / "workspace"
                archive_base(source, workspace)
                write_json(root / "baseline.json", inventory(workspace))
                for name in SOURCE_FILES:
                    destination = relative_file(workspace, name)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with destination.open("xb") as handle:
                        handle.write((Path(source["workspace"]) / name).read_bytes())
                before = inventory(workspace)
                write_json(root / "before-tree.json", before)
                shutil.copyfile(patch, root / "repair.patch")
                if file_hash(root / "repair.patch") != PATCH_SHA256:
                    raise ValueError("Reviewed patch changed during copy")
                request = ManualRepairRequest(
                    schema_version="1.0",
                    kind="ManualTechnicalRepairRequest",
                    repair_id=identifier,
                    source_attempt_id=source_id,
                    task_id=source["task_id"],
                    candidate_id=original_request.candidate_id,
                    operation=OPERATION,
                    author=author,
                    authorization=authorization,
                    source_receipt_sha256=file_hash(source_receipt_path),
                    patch_sha256=PATCH_SHA256,
                    base_commit=source["base_commit"],
                    source_files=SOURCE_FILES,
                    target_version="1.0.1",
                    version_amendment="Approved compatibility1.0.0->1.0.1; "
                    "immutable hypothesis and trading rules retained",
                    model_calls_permitted=0,
                )
                write_json(root / "request.json", request.model_dump(mode="json"))
                native_request = original_request.model_copy(
                    update={
                        "attempt_id": identifier,
                        "workspace": str(workspace),
                        "branch": "snapshot:" + identifier,
                        "native_interface_check": "SYNTHETIC_OHLCV_UTC_V1",
                    }
                )
                # Source attempt number is provenance; the descriptor does not reset a counter.
                write_json(root / "native-request.json", native_request.model_dump(mode="json"))
                # The fixed bridge reads request.json from a separate native-control root.
                native_root = root / "native-control"
                native_root.mkdir()
                write_json(native_root / "request.json", native_request.model_dump(mode="json"))
                with self.store.transaction() as conn:
                    conn.execute(
                        "UPDATE manual_repairs SET request_sha256=?,seal_sha256=? "
                        "WHERE repair_id=?",
                        (file_hash(root / "request.json"), self._seal(root), identifier),
                    )
                applied = run_process(
                    [
                        "git",
                        "-c",
                        "core.autocrlf=false",
                        "apply",
                        "--whitespace=error",
                        str(root / "repair.patch"),
                    ],
                    workspace,
                    15,
                    root / "apply.stdout",
                    root / "apply.stderr",
                    on_start=lambda pid: self._pid(identifier, pid),
                )
                write_json(root / "apply-process.json", applied)
                if applied["exit_code"] or applied["timed_out"]:
                    raise ValueError("Reviewed patch could not be applied; inspect apply logs")
                after = inventory(workspace)
                changed = {name: sha for name, sha in after.items() if before.get(name) != sha}
                if changed != TARGET_FILES or set(before) != set(after):
                    raise ValueError("Manual patch changed unexpected files")
                descriptor = {"attempt_id": identifier, "root": str(native_root)}
                checks = []
                for index, command in enumerate(native_request.plan.checks()):
                    if index == 0:
                        command = [*command, "--basetemp", str(root / "regression-temp")]
                    process = run_process(
                        [sys.executable, *command[1:]],
                        workspace,
                        60,
                        root / f"check-{index}.stdout",
                        root / f"check-{index}.stderr",
                        on_start=lambda pid: self._pid(identifier, pid),
                    )
                    process["authorized_argv"] = command
                    checks.append(process)
                    write_json(root / f"check-{index}.json", process)
                    if process["exit_code"] or process["timed_out"]:
                        raise ValueError("Independent manual repair check failed")
                if file_hash(native_root / "request.json") != file_hash(
                    root / "native-request.json"
                ):
                    raise ValueError("Native descriptor changed during tests")
                native = Coordinator(self.store)._native_interface(
                    descriptor,
                    native_request,
                    root / "native-evidence",
                    30,
                    on_start=lambda pid: self._pid(identifier, pid),
                )
                if inventory(workspace) != after:
                    raise ValueError("Manual repair workspace changed during verification")
                verified_implementation(
                    self.store, source_id
                )  # Source stayed untouched throughout.
                write_json(root / "final-tree.json", after)
                receipt = {
                    "schema_version": "1.0",
                    "kind": "ManualImplementationReceipt",
                    "status": "IMPLEMENTED_VERIFIED",
                    "implementation_id": identifier,
                    "task_id": request.task_id,
                    "candidate_id": request.candidate_id,
                    "source_attempt_id": source_id,
                    "source_receipt": str(source_receipt_path),
                    "source_receipt_sha256": request.source_receipt_sha256,
                    "request_sha256": file_hash(root / "request.json"),
                    "source_operator_format_repair": source_receipt.get("operator_format_repair"),
                    "base_commit": request.base_commit,
                    "files": changed,
                    "author": request.author,
                    "authorization": request.authorization,
                    "origin": "AUTHORIZED_MANUAL_TECHNICAL_REPAIR",
                    "version_amendment": request.version_amendment,
                    "model_invocations": 0,
                    "model_attempts_consumed": 3,
                    "native_interface": native,
                    "checks": checks,
                    "patch_sha256": PATCH_SHA256,
                    "economic_assessment": "NOT_ASSESSED",
                    "demo_authorized": False,
                    "created_at_utc": utc_now(),
                }
                write_json(root / "receipt.json", receipt)
                hashes = {
                    p.relative_to(root).as_posix(): file_hash(p)
                    for p in root.rglob("*")
                    if p.is_file() and not p.is_relative_to(workspace)
                }
                write_json(root / "hashes.json", hashes)
                with self.store.transaction() as conn:
                    conn.execute(
                        "UPDATE manual_repairs SET receipt_path=?,receipt_sha256=?,"
                        "artifacts_sha256=? "
                        "WHERE repair_id=?",
                        (
                            str(root / "receipt.json"),
                            file_hash(root / "receipt.json"),
                            file_hash(root / "hashes.json"),
                            identifier,
                        ),
                    )
                return self._state(
                    identifier, "SUCCEEDED", "New verified manual implementation: " + identifier
                )
            except BaseException as exc:
                state = (
                    "FAILED"
                    if isinstance(exc, (OSError, ValueError, subprocess.SubprocessError))
                    else "UNKNOWN"
                )
                self._state(identifier, state, "Manual repair: " + str(exc))
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                return self.get(identifier)

    def verified(self, identifier):
        from .execution_inputs import relative_file, verified_implementation

        row = self.get(identifier)
        if row["status"] != "SUCCEEDED" or pending(row):
            raise ValueError("Manual implementation is not verified/stopped")
        root = Path(row["root"])
        if (
            file_hash(root / "request.json") != row["request_sha256"]
            or self._seal(root) != row["seal_sha256"]
        ):
            raise ValueError("Manual repair controls changed")
        request = ManualRepairRequest.model_validate_json((root / "request.json").read_text())
        if request.repair_id != identifier or request.source_attempt_id != row["source_attempt_id"]:
            raise ValueError("Manual request identity mismatch")
        source, _, source_path, _ = verified_implementation(self.store, row["source_attempt_id"])
        if request.source_receipt_sha256 != file_hash(source_path):
            raise ValueError("Manual repair source provenance changed")
        if file_hash(root / "receipt.json") != row["receipt_sha256"]:
            raise ValueError("Manual repair receipt changed")
        if file_hash(root / "hashes.json") != row["artifacts_sha256"]:
            raise ValueError("Manual evidence manifest changed")
        for name, sha in json.loads((root / "hashes.json").read_text()).items():
            if file_hash(relative_file(root, name)) != sha:
                raise ValueError("Manual verification artifact changed")
        if inventory(root / "workspace") != json.loads((root / "final-tree.json").read_text()):
            raise ValueError("Manual implementation changed after verification")
        receipt = json.loads((root / "receipt.json").read_text())
        baseline = json.loads((root / "baseline.json").read_text())
        tree = json.loads((root / "final-tree.json").read_text())
        changed = {name: sha for name, sha in tree.items() if baseline.get(name) != sha}
        if (
            receipt["status"] != "IMPLEMENTED_VERIFIED"
            or receipt["files"] != changed
            or changed != TARGET_FILES
        ):
            raise ValueError("Manual final file identity mismatch")
        if (
            any(check["exit_code"] or check["timed_out"] for check in receipt["checks"])
            or receipt["native_interface"]["report"]["status"] != "VALID"
        ):
            raise ValueError("Manual receipt checks do not support verification")
        if (
            receipt["implementation_id"] != identifier
            or receipt["request_sha256"] != row["request_sha256"]
        ):
            raise ValueError("Manual receipt identity mismatch")
        native = ImplementationRequest.model_validate_json(
            (root / "native-request.json").read_text()
        )
        materialized = source | {
            "attempt_id": identifier,
            "parent_attempt_id": source["attempt_id"],
            "root": str(root),
            "workspace": str(root / "workspace"),
            "request_sha256": row["request_sha256"],
            "manual_repair_id": identifier,
        }
        return materialized, native, root / "receipt.json", receipt

    def reconcile(self, identifier, confirm_stopped, reason):
        if not confirm_stopped or not reason.strip():
            raise ValueError("Explicit stopped confirmation and reason required")
        with coordinator_lock(self.lock):
            row = self.get(identifier)
            if row["status"] not in {"RUNNING", "UNKNOWN"} or pending(row):
                raise ValueError("Reconciliation requires an uncertain stopped manual repair")
            return self._state(identifier, "FAILED", "Confirmed manual repair failure: " + reason)
