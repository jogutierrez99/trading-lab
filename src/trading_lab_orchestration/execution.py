"""Manual deterministic execution lifecycle, separate from implementation and economics."""

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from .contracts import canonical, digest
from .execution_contracts import ExecutionPlan, ExecutionRequest
from .execution_inputs import prepare_inputs, resolve_implementation, verify_hashes
from .process_identity import inspected, pending, record_process
from .processes import coordinator_lock, run_process
from .store import utc_now
from .workspaces import file_hash, inventory, write_json

ACTIVE = "('PREPARED','RUNNING','UNKNOWN')"


class Executor:
    def __init__(self, store):
        self.store = store
        self.lock = store.path.with_suffix(".implementation.lock")

    def get(self, identifier):
        with self.store.connection() as conn:
            row = conn.execute(
                "SELECT * FROM executions WHERE execution_id=?", (identifier,)
            ).fetchone()
        if not row:
            raise ValueError("Unknown execution_id")
        return inspected(row)

    def inspect(self, identifier):
        row = self.get(identifier)
        if row["status"] == "RUNNING":
            try:
                with coordinator_lock(self.lock):
                    if self.get(identifier)["status"] == "RUNNING":
                        row = self._state(
                            identifier, "UNKNOWN", "Execution owner disappeared; reconcile"
                        )
            except ValueError:
                pass
        return row

    def _state(self, identifier, status, reason):
        with self.store.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM executions WHERE execution_id=?", (identifier,)
            ).fetchone()
            conn.execute(
                "UPDATE executions SET status=?,error=?,ended_at_utc=? WHERE execution_id=?",
                (
                    status,
                    reason,
                    None if status in {"RUNNING", "UNKNOWN"} else utc_now(),
                    identifier,
                ),
            )
            task = conn.execute("SELECT * FROM tasks WHERE task_id=?", (row["task_id"],)).fetchone()
            self.store._event(
                conn,
                task["candidate_id"],
                task["task_id"],
                "task",
                task["status"],
                task["status"],
                reason,
                {
                    "execution_id": identifier,
                    "old_execution_status": row["status"],
                    "execution_status": status,
                },
                actor="deterministic_executor",
            )
        return self.get(identifier)

    def _pid(self, identifier, pid):
        with self.store.transaction() as conn:
            record_process(conn, "executions", "execution_id", identifier, pid)

    @staticmethod
    def _seal(root):
        return digest(
            canonical(
                {
                    name: file_hash(root / name)
                    for name in (
                        "workspace-files.json",
                        "adaptations.json",
                        "implementation-receipt.json",
                    )
                }
            )
        )

    def prepare(self, implementation_id, plan, artifacts, retry_of=None):
        plan = ExecutionPlan.model_validate_json(canonical(plan.model_dump(mode="json")))
        with coordinator_lock(self.lock):
            attempt, implementation, receipt_path, receipt = resolve_implementation(
                self.store, implementation_id
            )
            root = Path(artifacts).resolve() / ("execution_" + uuid4().hex)
            for protected in [
                Path(attempt["repo"]),
                Path(attempt["root"]),
                *(Path(d.path) for d in plan.datasets),
            ]:
                if root.is_relative_to(protected.resolve()) or protected.resolve().is_relative_to(
                    root
                ):
                    raise ValueError(
                        "Execution artifacts must be separate from repository, "
                        "implementation and datasets"
                    )
            intent = digest(
                canonical(
                    {
                        "implementation": implementation_id,
                        "receipt": file_hash(receipt_path),
                        "plan": plan.model_dump(mode="json", exclude_none=True),
                    }
                )
            )
            identifier = root.name
            with self.store.transaction() as conn:
                if (
                    conn.execute(f"SELECT 1 FROM attempts WHERE status IN {ACTIVE}").fetchone()
                    or conn.execute(f"SELECT 1 FROM executions WHERE status IN {ACTIVE}").fetchone()
                    or conn.execute(
                        "SELECT 1 FROM manual_repairs WHERE status IN ('RUNNING','UNKNOWN')"
                    ).fetchone()
                ):
                    raise ValueError(
                        "One heavy job is active or uncertain; inspect/reconcile first"
                    )
                previous = conn.execute(
                    "SELECT * FROM executions WHERE intent_sha256=? ORDER BY created_at_utc DESC",
                    (intent,),
                ).fetchone()
                if previous:
                    if retry_of != previous["execution_id"] or previous["status"] not in {
                        "FAILED",
                        "TIMED_OUT",
                        "BLOCKED",
                        "CANCELLED",
                    }:
                        raise ValueError(
                            "Duplicate execution intent; use retry-of for a confirmed failure"
                        )
                    if pending(previous):
                        raise ValueError("Previous execution process still exists")
                elif retry_of:
                    raise ValueError("Retry must retain the exact implementation, receipt and plan")
                conn.execute(
                    """INSERT INTO executions(execution_id,task_id,attempt_id,intent_sha256,
                    status,root,created_at_utc,retry_of,manual_repair_id)
                    VALUES (?,?,?,?,'PREPARED',?,?,?,?)""",
                    (
                        identifier,
                        attempt["task_id"],
                        attempt.get("parent_attempt_id", implementation_id),
                        intent,
                        str(root),
                        utc_now(),
                        retry_of,
                        attempt.get("manual_repair_id"),
                    ),
                )
                self.store._event(
                    conn,
                    implementation.candidate_id,
                    attempt["task_id"],
                    "task",
                    "SUCCEEDED",
                    "SUCCEEDED",
                    "Manual backtest reservation",
                    {"execution_id": identifier, "execution_status": "PREPARED"},
                    actor="deterministic_executor",
                )
            try:
                root.mkdir(parents=True, exist_ok=False)
                if plan.comparison:
                    from .rmm_comparison import prepare_comparison_inputs

                    inputs, tree = prepare_comparison_inputs(
                        root, attempt, implementation, receipt, plan
                    )
                else:
                    inputs, tree = prepare_inputs(root, attempt, implementation, receipt, plan)
                runtime_root = Path(__file__).resolve().parents[2]
                sources = [
                    runtime_root / "scripts/run_coordinated_backtest.py",
                    *Path(__file__).parent.glob("*.py"),
                ]
                runtime = {}
                for source in sources:
                    archived = root / "runtime" / source.relative_to(runtime_root)
                    archived.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, archived)
                    runtime[str(archived)] = file_hash(archived)
                entry = root / "runtime/scripts/run_coordinated_backtest.py"
                request = ExecutionRequest(
                    schema_version="1.0",
                    kind="BacktestExecutionRequest",
                    execution_id=identifier,
                    task_id=attempt["task_id"],
                    candidate_id=implementation.candidate_id,
                    implementation_id=implementation_id,
                    source_attempt_id=attempt.get("parent_attempt_id"),
                    implementation_origin="MANUAL_TECHNICAL_REPAIR"
                    if attempt.get("manual_repair_id")
                    else "CODEX_CLI",
                    source_implementation_receipt_sha256=receipt.get("source_receipt_sha256"),
                    implementation_receipt=str(receipt_path),
                    implementation_receipt_sha256=file_hash(receipt_path),
                    implementation_final_files=receipt["files"],
                    operator_format_repair=receipt.get("operator_format_repair"),
                    base_commit=attempt["base_commit"],
                    implementation_request_sha256=attempt["request_sha256"],
                    workspace=str(root / "workspace"),
                    experiment=str(root / "workspace/execution-config/experiment.yaml"),
                    results=str(root / "results"),
                    runner_entrypoint=str(entry),
                    runtime_files=runtime,
                    input_files=inputs,
                    plan=plan,
                )
                write_json(root / "workspace-files.json", tree)
                encoded = request.model_dump(mode="json")
                if not plan.comparison:
                    encoded["plan"].pop("comparison")
                write_json(root / "request.json", encoded)
                with self.store.transaction() as conn:
                    conn.execute(
                        "UPDATE executions SET request_sha256=?,seal_sha256=? WHERE execution_id=?",
                        (file_hash(root / "request.json"), self._seal(root), identifier),
                    )
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                return self._state(identifier, "BLOCKED", "Preparation blocked: " + str(exc))
            return self.get(identifier)

    def _load(self, row):
        root = Path(row["root"])
        if (
            file_hash(root / "request.json") != row["request_sha256"]
            or self._seal(root) != row["seal_sha256"]
        ):
            raise ValueError("Execution request/control artifacts changed")
        request = ExecutionRequest.model_validate_json((root / "request.json").read_text())
        if request.execution_id != row["execution_id"] or request.implementation_id != (
            row["manual_repair_id"] or row["attempt_id"]
        ):
            raise ValueError("Execution request identity mismatch")
        if row["manual_repair_id"] and (
            request.source_attempt_id != row["attempt_id"]
            or request.implementation_origin != "MANUAL_TECHNICAL_REPAIR"
        ):
            raise ValueError("Manual execution provenance mismatch")
        _, _, path, receipt = resolve_implementation(self.store, request.implementation_id)
        if (
            file_hash(path) != request.implementation_receipt_sha256
            or receipt["files"] != request.implementation_final_files
        ):
            raise ValueError("Implementation receipt/final identity changed")
        verify_hashes(request.input_files | request.runtime_files)
        if inventory(Path(request.workspace)) != json.loads(
            (root / "workspace-files.json").read_text()
        ):
            raise ValueError("Execution workspace changed")
        return request

    def _command(self, request, action, result):
        return [
            sys.executable,
            "-I",
            "-B",
            request.runner_entrypoint,
            action,
            "--request",
            str(Path(request.workspace).parent / "request.json"),
            "--result",
            str(result),
        ]

    def validate(self, identifier):
        with coordinator_lock(self.lock):
            row = self.get(identifier)
            if row["status"] != "PREPARED":
                raise ValueError("Only a prepared execution can be validated")
            root = Path(row["root"])
            try:
                request = self._load(row)
                approval = root / "validation-approved.json"
                if approval.exists():
                    self._approval(row)
                    return row | {"validation": "FULL", "already_validated": True}
                directory = root / ("validation_" + uuid4().hex)
                directory.mkdir()
                result = directory / "result.json"
                process = run_process(
                    self._command(request, "validate", result),
                    Path(request.workspace),
                    request.plan.validation_timeout_seconds,
                    directory / "stdout",
                    directory / "stderr",
                    on_start=lambda pid: self._pid(identifier, pid),
                )
                write_json(directory / "process.json", process)
                if process["exit_code"] or process["timed_out"]:
                    detail = (
                        json.loads(result.read_text()).get("error")
                        if result.exists()
                        else "timeout/no result"
                    )
                    raise ValueError(
                        f"Native FULL/interface validation failed: {detail}; inspect {directory}"
                    )
                report = json.loads(result.read_text())
                if report["status"] != "VALID":
                    raise ValueError("Native validator did not return VALID")
                self._load(self.get(identifier))
                write_json(
                    approval,
                    {
                        "request_sha256": row["request_sha256"],
                        "result": str(result),
                        "sha256": file_hash(result),
                        "report": report,
                    },
                )
                return self.get(identifier) | {"validation": "FULL", "report": report}
            except (OSError, ValueError, KeyError) as exc:
                return self._state(identifier, "BLOCKED", str(exc))

    @staticmethod
    def _approval(row):
        approval = json.loads((Path(row["root"]) / "validation-approved.json").read_text())
        if (
            approval["request_sha256"] != row["request_sha256"]
            or file_hash(Path(approval["result"])) != approval["sha256"]
        ):
            raise ValueError("Full validation evidence changed")
        report = json.loads(Path(approval["result"]).read_text())
        if report != approval["report"] or report["status"] != "VALID":
            raise ValueError("Full validation approval contradicts native report")
        return report

    def run(self, identifier):
        with coordinator_lock(self.lock):
            row = self.get(identifier)
            if row["status"] != "PREPARED":
                raise ValueError("Execution cannot be relaunched; inspect/reconcile first")
            try:
                request = self._load(row)
                self._approval(row)
            except (OSError, ValueError, KeyError) as exc:
                return self._state(identifier, "BLOCKED", "Preflight blocked: " + str(exc))
            root = Path(row["root"])
            if (root / "results").exists() or (
                request.plan.comparison and (root / "comparison-baseline").exists()
            ):
                return self._state(
                    identifier, "BLOCKED", "Results already exist; refusing relaunch"
                )
            self._state(identifier, "RUNNING", "Manual deterministic backtest started")
            with self.store.transaction() as conn:
                conn.execute(
                    "UPDATE executions SET started_at_utc=? WHERE execution_id=?",
                    (utc_now(), identifier),
                )
            try:
                process = run_process(
                    self._command(request, "run", root / "runner-result.json"),
                    Path(request.workspace),
                    request.plan.max_wall_seconds,
                    root / "runner.stdout",
                    root / "runner.stderr",
                    on_start=lambda pid: self._pid(identifier, pid),
                )
                write_json(root / "process-result.json", process)
                return self._finalize(identifier)
            except BaseException as exc:
                self._state(identifier, "UNKNOWN", "Interrupted execution: " + type(exc).__name__)
                if isinstance(exc, (SystemExit, KeyboardInterrupt)):
                    raise
                return self.get(identifier)

    def _finalize(self, identifier):
        row = self.get(identifier)
        root = Path(row["root"])
        request = self._load(row)
        expected = self._approval(row)["backtests"]
        process = json.loads((root / "process-result.json").read_text())
        if process["argv"] != self._command(request, "run", root / "runner-result.json"):
            raise ValueError("Recorded runner command contradicts the fixed execution command")
        state = (
            "TIMED_OUT"
            if process["timed_out"]
            else "FAILED"
            if process["exit_code"]
            else "SUCCEEDED"
        )
        run_id, native = None, None
        runs = list((root / "results").glob("*/*/run.json"))
        if len(runs) > 1:
            raise ValueError("Ambiguous runner directories")
        if runs:
            run_meta = json.loads(runs[0].read_text())
            run_id = run_meta["run_id"]
            if run_id != runs[0].parent.name or run_meta["expected_backtests"] != expected:
                raise ValueError("Native run identity/count contradicts request")
            outcome = runs[0].parent / "outcome.json"
            native = (
                json.loads(outcome.read_text()) if outcome.exists() else {"status": "INCOMPLETE"}
            )
        if state == "SUCCEEDED":
            result = json.loads((root / "runner-result.json").read_text())
            if (
                not runs
                or result["run_id"] != run_id
                or Path(result["run_directory"]).resolve() != runs[0].parent.resolve()
            ):
                raise ValueError("Worker/run identity mismatch")
            if native != {"status": "COMPLETE", "backtests": expected}:
                raise ValueError("Native outcome is not COMPLETE with expected backtests")
            with sqlite3.connect(runs[0].parent / "ledger.sqlite") as conn:
                records = conn.execute("SELECT id,status,result_sha256 FROM experiments").fetchall()
            if len(records) != expected or any(
                status != "completed" or file_hash(runs[0].parent / name / "result.json") != sha
                for name, status, sha in records
            ):
                raise ValueError("Native experiment ledger incomplete or hashes changed")
            if request.plan.comparison:
                from .rmm_comparison import verify_comparison_results

                verify_comparison_results(
                    root, request, runs[0].parent, result, self._approval(row)
                )
        evidence = root / ("verification_" + uuid4().hex)
        evidence.mkdir()
        artifacts = {}
        for path in root.rglob("*"):
            if path.is_file() and not path.is_relative_to(Path(request.workspace)):
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    raise ValueError("Linked execution artifact")
                artifacts[path.relative_to(root).as_posix()] = file_hash(path)
        receipt = {
            "schema_version": "1.0",
            "kind": "BacktestExecutionReceipt",
            "execution_id": identifier,
            "task_id": request.task_id,
            "candidate_id": request.candidate_id,
            "implementation_id": request.implementation_id,
            "source_attempt_id": row["attempt_id"],
            "manual_repair_id": row["manual_repair_id"],
            "implementation_origin": request.implementation_origin,
            "source_implementation_receipt_sha256": request.source_implementation_receipt_sha256,
            "request_sha256": row["request_sha256"],
            "implementation_receipt_sha256": request.implementation_receipt_sha256,
            "base_commit": request.base_commit,
            "implementation_final_files": request.implementation_final_files,
            "operator_format_repair": request.operator_format_repair,
            "command": process["argv"],
            "started_at_utc": row["started_at_utc"],
            "ended_at_utc": utc_now(),
            "process": process,
            "execution_status": state,
            "runner_outcome": native,
            "run_id": run_id,
            "artifacts_sha256": artifacts,
            "economic_assessment": "NOT_ASSESSED",
            "demo_authorized": False,
            "scope": request.plan.scope,
            "native_classifications": "Unchanged in hashed native summary/leaderboard/results",
        }
        write_json(evidence / "receipt.json", receipt)
        write_json(evidence / "hashes.json", {"receipt.json": file_hash(evidence / "receipt.json")})
        return self._state(
            identifier, state, "Execution receipt: " + str(evidence / "receipt.json")
        )

    def reconcile(self, identifier, outcome, confirm_stopped, reason):
        if (
            not confirm_stopped
            or not reason.strip()
            or outcome not in {"verify", "failed", "cancel"}
        ):
            raise ValueError("Explicit stopped confirmation, outcome and reason are required")
        with coordinator_lock(self.lock):
            row = self.get(identifier)
            eligible = row["status"] in {"RUNNING", "UNKNOWN"} or (
                row["status"] == "PREPARED" and outcome == "cancel"
            )
            if not eligible or pending(row):
                raise ValueError(
                    "Reconciliation requires uncertain execution and stopped recorded PID"
                )
            self._state(identifier, "UNKNOWN", "Manual execution reconciliation: " + reason)
            if outcome != "verify":
                return self._state(
                    identifier, "FAILED" if outcome == "failed" else "CANCELLED", reason
                )
            try:
                return self._finalize(identifier)
            except (OSError, ValueError, KeyError) as exc:
                return self._state(
                    identifier, "UNKNOWN", "Evidence cannot establish completion: " + str(exc)
                )
