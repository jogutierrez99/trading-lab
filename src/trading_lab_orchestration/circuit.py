"""Thin manual-start connector for existing stages. Never sends Telegram or repairs files."""

import json
import os
import time
from pathlib import Path
from uuid import uuid4

from .audit import Auditor
from .audit_contracts import AuditRequest
from .audit_evidence import Evidence, review
from .audit_notifications import Outbox
from .circuit_contracts import (
    ACCEPTANCE_RESEARCHER,
    FLOW1_RESEARCHER,
    CircuitRequest,
    technical_profile,
)
from .circuit_fixture import prepare_circuit_fixture, verify_circuit_coverage
from .codex_adapter import CodexCLI
from .contracts import canonical, digest
from .execution import Executor
from .execution_contracts import ExecutionPlan
from .execution_inputs import resolve_implementation
from .implementation import Coordinator, review_spec
from .process_identity import _valid, inspected, pending
from .processes import coordinator_lock
from .readonly import ReadOnlyStore
from .store import utc_now
from .workspaces import file_hash, git, write_json

FLOW1_PAUSE = "Flow 1: deterministic audit ready; reconcile research and complete OpenAI audit"


def check_acceptance_database(database, request):
    if request.manifest.researcher_version != ACCEPTANCE_RESEARCHER:
        return
    if os.name != "nt":
        raise ValueError("The final acceptance profile requires Windows")
    if Path(database).exists():
        with ReadOnlyStore(Path(database)).connection() as conn:
            if conn.execute("PRAGMA user_version").fetchone()[0] != 7:
                raise ValueError("Acceptance requires a separate new or dedicated v7 database")
            if (
                conn.execute(
                    "SELECT 1 FROM circuits WHERE circuit_id<>?", (request.circuit_id,)
                ).fetchone()
                or conn.execute(
                    "SELECT 1 FROM candidates WHERE hypothesis_id<>?",
                    (request.manifest.hypothesis_id,),
                ).fetchone()
            ):
                raise ValueError("Acceptance database contains a different dossier")


def verify_acceptance_processes(store, attempt_id, execution, execution_receipt):
    attempt, _, _, implementation = resolve_implementation(store, attempt_id)
    if implementation["operator_format_repair"] is not None:
        raise ValueError("Acceptance requires a delivery without manual format repair")
    model = implementation["process"]
    probe = implementation["native_interface"]["process"]
    runner = json.loads(Path(execution_receipt).read_text(encoding="utf-8"))["process"]
    identities = {}
    for label, process, row in (
        ("model", model, None),
        ("native_probe", probe, attempt),
        ("runner", runner, execution),
    ):
        birth = process.get("process_identity")
        if not _valid(birth, process.get("pid")) or birth["clock"] != "WINDOWS_FILETIME_100NS":
            raise ValueError(f"Missing native Windows birth identity for {label}")
        if row is not None and (
            row["child_pid"] != birth["pid"]
            or json.loads(row.get("process_identity_json") or "null") != birth
        ):
            raise ValueError(f"SQLite process identity contradicts the {label} receipt")
        identities[label] = birth
    return identities


def circuit_doctor(database, request, repo, artifacts, executable="codex"):
    """Offline preflight: never run Codex, inspect auth files or contact a provider."""
    request = CircuitRequest.model_validate_json(request.model_dump_json())
    check_acceptance_database(database, request)
    review_spec(request.manifest, request.implementation)
    repo = Path(git(Path(repo).resolve(), "rev-parse", "--show-toplevel"))
    base = git(repo, "rev-parse", "HEAD")
    root = Path(artifacts).resolve() / request.circuit_id
    if root.exists():
        raise ValueError(
            "Circuit artifact destination exists; inspect/resume its owner, never overwrite"
        )
    if root.is_relative_to(repo) or root.is_relative_to(Path(database).resolve().parent):
        raise ValueError("Circuit artifacts must be outside repository and database directory")
    for name in request.implementation.paths():
        if (repo / name).exists() or git(repo, "ls-tree", "--name-only", base, "--", name):
            raise ValueError("Technical target collides with an existing strategy/config/test")
    command = CodexCLI(executable).command  # Resolution only; no version/login/model invocation.
    if Path(database).is_file():
        with ReadOnlyStore(Path(database)).connection() as c:
            for table, active in (
                ("attempts", "('PREPARED','RUNNING','UNKNOWN')"),
                ("executions", "('PREPARED','RUNNING','UNKNOWN')"),
                ("manual_repairs", "('RUNNING','UNKNOWN')"),
            ):
                if c.execute("SELECT 1 FROM " + table + " WHERE status IN " + active).fetchone():
                    raise ValueError("Active/uncertain work exists; reconcile before a new circuit")
    return {
        "schema_version": "1.0",
        "status": "LOCAL_PREFLIGHT_OK",
        "repo": str(repo),
        "base_commit": base,
        "root": str(root),
        "command": command,
        "limits": {
            "initial": 1,
            "technical_repairs": 2,
            "attempt_wall_seconds": 300,
            "check_timeout_seconds": 45,
            "execution_seconds": 120,
            "validation_seconds": 60,
            "backtests": 6,
            "candles": 328,
            "dataset_bytes": 2000000,
            "invocation_seconds": 1500,
        },
        "authentication": "NOT_CHECKED; bounded CLI preflight happens on operator launch",
        "sandbox": "Existing workspace-write, no network tools, never approvals; unchanged",
        "auditor": "DETERMINISTIC_ONLY",
        "telegram": "PREVIEW_ONLY",
        "network_calls": 0,
    }


class CircuitRunner:
    def __init__(self, store, *, simulated=False):
        self.store = store
        self.simulated = simulated
        self.on_progress = lambda event: None
        self.coordinator, self.executor = Coordinator(store), Executor(store)
        self.auditor, self.outbox = Auditor(store), Outbox(store)
        self.lock = store.path.with_suffix(".circuit.lock")

    def get(self, identifier):
        with self.store.connection() as c:
            row = c.execute("SELECT * FROM circuits WHERE circuit_id=?", (identifier,)).fetchone()
        if not row:
            raise ValueError("Unknown circuit_id")
        return dict(row)

    def _update(self, identifier, **values):
        allowed = {
            "task_id",
            "attempt_id",
            "execution_id",
            "audit_id",
            "notification_id",
            "status",
            "active_stage",
            "error",
            "evidence_json",
        }
        if not values.keys() <= allowed:
            raise ValueError("Invalid circuit checkpoint fields")
        values["updated_at_utc"] = utc_now()
        with self.store.transaction() as c:
            c.execute(
                "UPDATE circuits SET " + ",".join(k + "=?" for k in values) + " WHERE circuit_id=?",
                (*values.values(), identifier),
            )

    def inspect(self, identifier):
        row = self.get(identifier)
        attempts = []
        if row["task_id"]:
            with self.store.connection() as c:
                attempts = [
                    inspected(a)
                    for a in c.execute(
                        "SELECT * FROM attempts WHERE task_id=? ORDER BY number",
                        (row["task_id"],),
                    )
                ]
        row["attempts"] = attempts
        row["attempts_used"] = len(attempts)
        row["repairs_used"] = max(0, len(attempts) - 1)
        row["success_on_initial_attempt"] = (
            row["status"] == "NOTICE_PREPARED" and len(attempts) == 1
        )
        row["success_after_repair"] = row["status"] == "NOTICE_PREPARED" and len(attempts) > 1
        row["real_test_acceptance"] = (
            "SIMULATED_ONLY; real4.6 remains pending"
            if row["simulated"]
            else "REVIEW_REAL_RECEIPTS; no automatic scientific/demo acceptance"
        )
        row["economic_validation"] = row["demo_authorized"] = False
        if row["status"] == "BLOCKED" and row["error"] == FLOW1_PAUSE:
            row["status"] = "AWAITING_MODEL_AUDIT"
        row["operator_resume_used"] = any(
            name.startswith("operator_resume_") for name in json.loads(row["evidence_json"])
        )
        for name, sha in json.loads(row["evidence_json"]).items():
            path = Path(row["root"]) / name
            if file_hash(path) != sha:
                raise ValueError("Circuit stage evidence changed")
            if name == "flow1-model-audit.json":
                model = json.loads(path.read_text(encoding="utf-8"))
                if file_hash(Path(model["receipt"])) != model["sha256"]:
                    raise ValueError("Flow 1 OpenAI audit receipt changed")
        if row["notification_id"]:
            row["preview"] = self.outbox.get(row["notification_id"])
            if row["preview"]["status"] in {"UNKNOWN", "SENDING"}:
                row["checkpoint_status"] = row["status"]
                row["status"] = "UNCERTAIN"
                row["requires_reconciliation"] = True
                row["success_on_initial_attempt"] = row["success_after_repair"] = False
        return row

    def start(self, request, repo, artifacts, executable="codex", *, resume=False):
        request = CircuitRequest.model_validate_json(request.model_dump_json())
        check_acceptance_database(self.store.path, request)
        encoded = canonical(request.model_dump(mode="json"))
        with coordinator_lock(self.lock):
            with self.store.connection() as c:
                existing = c.execute(
                    "SELECT * FROM circuits WHERE circuit_id=?", (request.circuit_id,)
                ).fetchone()
            if existing:
                if bool(existing["simulated"]) != self.simulated:
                    raise ValueError("Cannot change simulated/operator provenance on resume")
                if existing["request_sha256"] != digest(encoded):
                    raise ValueError("Circuit request changed; never reset or replace its budget")
                if (
                    not resume
                    or existing["status"] == "NOTICE_PREPARED"
                    or existing["error"] == FLOW1_PAUSE
                ):
                    return self.inspect(request.circuit_id)
                row = dict(existing)
                if Path(repo).resolve() != Path(row["repo"]):
                    raise ValueError("Resume must use the frozen repository")
                if CodexCLI(executable).command != json.loads(row["command_json"]):
                    raise ValueError("Resume cannot change the configured CLI")
            else:
                if resume:
                    raise ValueError("Cannot resume a nonexistent circuit")
                doctor = circuit_doctor(self.store.path, request, repo, artifacts, executable)
                self.on_progress({"event": "PREFLIGHT", **doctor})
                with self.store.transaction() as c:
                    adopted_task = None
                    if request.manifest.researcher_version == FLOW1_RESEARCHER:
                        candidate = c.execute(
                            "SELECT t.task_id,t.status,c.manifest_json FROM candidates c "
                            "JOIN tasks t USING(candidate_id) WHERE c.hypothesis_id=?",
                            (request.manifest.hypothesis_id,),
                        ).fetchone()
                        if (
                            not candidate
                            or candidate["status"] != "QUEUED"
                            or candidate["manifest_json"] != request.manifest.snapshot()
                            or c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] != 1
                            or c.execute("SELECT 1 FROM circuits").fetchone()
                        ):
                            raise ValueError(
                                "Flow 1 requires its exact QUEUED intake in an isolated database"
                            )
                        adopted_task = candidate["task_id"]
                    elif c.execute(
                        "SELECT 1 FROM candidates WHERE fingerprint=? OR hypothesis_id=?",
                        (request.manifest.fingerprint(), request.manifest.hypothesis_id),
                    ).fetchone():
                        raise ValueError(
                            "Existing hypothesis/candidate cannot be adopted to reset its budget"
                        )
                    c.execute(
                        "INSERT INTO circuits(circuit_id,request_sha256,request_json,repo,"
                        "base_commit,root,command_json,simulated,status,created_at_utc,"
                        "updated_at_utc,task_id) "
                        "VALUES(?,?,?,?,?,?,?,?,'PREPARED',?,?,?)",
                        (
                            request.circuit_id,
                            digest(encoded),
                            encoded,
                            doctor["repo"],
                            doctor["base_commit"],
                            doctor["root"],
                            canonical(doctor["command"]),
                            int(self.simulated),
                            utc_now(),
                            utc_now(),
                            adopted_task,
                        ),
                    )
                row = self.get(request.circuit_id)
            self.identifier, self.request = request.circuit_id, request
            self.deadline = time.monotonic() + request.max_invocation_seconds
            root = Path(row["root"])
            root.mkdir(parents=True, exist_ok=True)
            frozen = root / "circuit-request.json"
            if frozen.exists():
                if file_hash(frozen) != row["request_sha256"]:
                    raise ValueError("Frozen circuit request changed")
            else:
                write_json(frozen, request.model_dump(mode="json"))
            self.root, self.repo = root, Path(row["repo"])
            self.command = json.loads(row["command_json"])
            try:
                self.inspect(self.identifier)  # Verify all prior checkpoint receipt hashes.
                if resume and request.manifest.researcher_version == ACCEPTANCE_RESEARCHER:
                    marker = root / f"operator_resume_{uuid4().hex}.json"
                    write_json(
                        marker,
                        {
                            "at_utc": utc_now(),
                            "prior_status": row["status"],
                            "prior_stage": row["active_stage"],
                        },
                    )
                    evidence = json.loads(row["evidence_json"])
                    evidence[marker.name] = file_hash(marker)
                    self._update(self.identifier, evidence_json=canonical(evidence))
                if git(self.repo, "rev-parse", "HEAD") != row["base_commit"]:
                    raise ValueError("Repository base changed; no automatic continuation")
                if not self._resume_guard(row):
                    return self._publish(self.inspect(self.identifier))
                return self._publish(self._drive())
            except BaseException as exc:
                interrupted = isinstance(exc, (KeyboardInterrupt, SystemExit))
                uncertain = interrupted or self.get(self.identifier)["active_stage"] in {
                    "MODEL_RUN",
                    "VALIDATE",
                    "EXEC_RUN",
                }
                self._update(
                    self.identifier,
                    status="UNCERTAIN" if uncertain else "BLOCKED",
                    error=type(exc).__name__ + ": " + str(exc)[:600],
                )
                if interrupted:
                    raise
                return self._publish(self.inspect(self.identifier))

    def _publish(self, result):
        path = self.root / ("circuit-status_" + uuid4().hex + ".json")
        write_json(
            path,
            {
                "schema_version": "1.0",
                "kind": "CircuitOutcome",
                "timestamp_utc": utc_now(),
                "result": result,
            },
        )
        evidence = json.loads(self.get(self.identifier)["evidence_json"])
        evidence[path.name] = file_hash(path)
        self._update(self.identifier, evidence_json=canonical(evidence))
        return self.inspect(self.identifier) | {
            "outcome_receipt": str(path),
            "outcome_sha256": file_hash(path),
        }

    def _block(self, reason, uncertain=False):
        self._update(self.identifier, status="UNCERTAIN" if uncertain else "BLOCKED", error=reason)
        return self.inspect(self.identifier)

    def _resume_guard(self, row):
        stage = row["active_stage"]
        if stage in {"MODEL_RUN", "VALIDATE", "EXEC_RUN"}:
            if stage == "MODEL_RUN":
                child = self.coordinator.attempt(row["attempt_id"])
                safe = child["status"] in {"SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED"}
            else:
                child = self.executor.get(row["execution_id"])
                safe = (
                    child["status"] == "SUCCEEDED"
                    if stage == "EXEC_RUN"
                    else (Path(child["root"]) / "validation-approved.json").exists()
                )
            if not safe or pending(child):
                self._block(
                    "Interrupted/uncertain stage requires existing manual reconciliation; "
                    "no relaunch",
                    True,
                )
                return False
        if stage == "AUDIT" and row["execution_id"]:
            with self.store.connection() as c:
                partial = c.execute(
                    "SELECT 1 FROM audits WHERE execution_id=? AND status='PREPARED'",
                    (row["execution_id"],),
                ).fetchone()
            if partial:
                self._block("Partial audit requires audit-reconcile before circuit resume", True)
                return False
        if row["status"] == "BLOCKED" and stage not in {"MODEL_RUN", "VALIDATE", "EXEC_RUN"}:
            if row["attempt_id"]:
                attempt = self.coordinator.attempt(row["attempt_id"])
                if (
                    attempt["status"] == "FAILED"
                    and attempt["retry_allowed"]
                    and attempt["number"] < 3
                    and not pending(attempt)
                    and not row["execution_id"]
                ):
                    return True  # Explicit existing reconcile, never an automatic permission retry.
            raise ValueError(
                "Terminal circuit blocker; inspect its evidence, do not edit files to force success"
            )
        return True

    def _step(self, stage, function, pointer=None):
        if time.monotonic() >= self.deadline:
            raise ValueError("Circuit invocation time budget exhausted")
        self._update(self.identifier, status="RUNNING", active_stage=stage, error=None)
        self.on_progress({"event": "STAGE", "stage": stage, "circuit_id": self.identifier})
        start = time.monotonic()
        value = function()
        receipt = self.root / (stage.lower() + "_" + uuid4().hex + ".json")
        write_json(
            receipt,
            {
                "schema_version": "1.0",
                "stage": stage,
                "duration_seconds": time.monotonic() - start,
                "result": value,
                "timestamp_utc": utc_now(),
            },
        )
        row = self.get(self.identifier)
        evidence = json.loads(row["evidence_json"])
        evidence[receipt.name] = file_hash(receipt)
        update = {"active_stage": None, "evidence_json": canonical(evidence)}
        if pointer:
            update[pointer] = value[pointer]
        self._update(self.identifier, **update)
        return value

    def _drive(self):
        row = self.get(self.identifier)
        if not row["task_id"]:
            self._step("REGISTER", lambda: self.store.register(self.request.manifest), "task_id")
        row = self.get(self.identifier)
        task = row["task_id"]
        while True:
            with self.store.connection() as c:
                attempts = [
                    inspected(a)
                    for a in c.execute(
                        "SELECT * FROM attempts WHERE task_id=? ORDER BY number", (task,)
                    )
                ]
            if not attempts:
                attempt = self._step(
                    "PREPARE",
                    lambda: self.coordinator.prepare(
                        task, self.repo, self.root / "attempts", self.request.implementation
                    ),
                    "attempt_id",
                )
            else:
                attempt = attempts[-1]
                self._update(self.identifier, attempt_id=attempt["attempt_id"])
            if attempt["status"] == "SUCCEEDED":
                break
            if attempt["status"] in {"RUNNING", "UNKNOWN"} or pending(attempt):
                return self._block("Implementation is active/uncertain; reconcile it", True)
            if attempt["status"] != "PREPARED":
                if (
                    attempt["status"] not in {"FAILED", "TIMED_OUT"}
                    or not attempt["retry_allowed"]
                    or attempt["number"] >= 3
                ):
                    return self._block(
                        "Implementation blocked or technical budget exhausted; inspect attempts"
                    )
                attempt = self._step(
                    "PREPARE",
                    lambda: self.coordinator.prepare(
                        task,
                        self.repo,
                        self.root / "attempts",
                        self.request.implementation,
                        repair=True,
                    ),
                    "attempt_id",
                )
            if attempt["status"] != "PREPARED":
                return self._block("Implementation preparation blocked; no permission retry")
            self._step(
                "MODEL_RUN",
                lambda attempt=attempt: self.coordinator.run(attempt["attempt_id"], self.command),
            )
        row = self.get(self.identifier)
        plan_path = self.root / "inputs/execution-plan.json"
        if not plan_path.exists():
            if (self.root / "inputs").exists():
                return self._block("Incomplete fixture preserved; no automatic regeneration", True)
            self._step(
                "FIXTURE",
                lambda: prepare_circuit_fixture(
                    self.store, row["attempt_id"], self.root / "inputs"
                ).model_dump(mode="json"),
            )
        plan = ExecutionPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        for name in json.loads(self.get(self.identifier)["evidence_json"]):
            if name.startswith("fixture_"):
                frozen_plan = json.loads((self.root / name).read_text(encoding="utf-8"))["result"]
                if frozen_plan != plan.model_dump(mode="json"):
                    raise ValueError("Fixture execution plan changed after its checkpoint")
        if (
            plan.max_backtests != 6
            or plan.max_candles != 328
            or plan.max_wall_seconds != 120
            or plan.validation_timeout_seconds != 60
            or plan.max_dataset_bytes != 2000000
            or plan.scope != "SYNTHETIC_TECHNICAL"
            or len(plan.datasets) != 2
            or any(d.kind != "SYNTHETIC" for d in plan.datasets)
        ):
            raise ValueError("Circuit fixture bounds/scope changed")
        with self.store.connection() as c:
            executions = [
                dict(e) for e in c.execute("SELECT * FROM executions WHERE task_id=?", (task,))
            ]
        if len(executions) > 1:
            raise ValueError("Circuit has contradictory duplicate execution records")
        if executions:
            execution = executions[0]
            self._update(self.identifier, execution_id=execution["execution_id"])
            if execution["attempt_id"] != row["attempt_id"] or not execution["request_sha256"]:
                return self._block(
                    "Incomplete or mismatched execution reservation; reconcile", True
                )
        else:
            execution = self._step(
                "EXEC_PREPARE",
                lambda: self.executor.prepare(row["attempt_id"], plan, self.root / "executions"),
                "execution_id",
            )
        if execution["status"] == "PREPARED":
            validated = self._step(
                "VALIDATE", lambda: self.executor.validate(execution["execution_id"])
            )
            if validated["status"] != "PREPARED":
                return self._block("Native validation blocked; no backtest or strategy repair")
            execution = self._step("EXEC_RUN", lambda: self.executor.run(execution["execution_id"]))
        if execution["status"] != "SUCCEEDED":
            return self._block(
                "Execution did not succeed; never retry it automatically",
                execution["status"] in {"RUNNING", "UNKNOWN"},
            )
        request = self._audit_request(execution, technical_profile(self.request.manifest)[2])
        native = review(self.store, request, Evidence(request))
        coverage = verify_circuit_coverage(native)
        self._step("COVERAGE", lambda: {"cases": coverage, "economic_assessment": "NOT_ASSESSED"})
        if self.request.manifest.researcher_version == ACCEPTANCE_RESEARCHER:
            self._step(
                "PROCESS_IDENTITY",
                lambda: verify_acceptance_processes(
                    self.store, row["attempt_id"], execution, request.execution_receipt
                ),
            )
        audited = self._step(
            "AUDIT", lambda: self.auditor.run(request, self.root / "audits"), "audit_id"
        )
        if audited["status"] != "COMPLETED_WITH_LIMITATIONS":
            return self._block("Deterministic evidence audit blocked")
        if self.request.manifest.researcher_version == FLOW1_RESEARCHER:
            return self._block(FLOW1_PAUSE)
        return self._prepare_notice(audited["audit_id"])

    def _prepare_notice(self, audit_id):
        notice = self._step("NOTICE", lambda: self.outbox.preview(audit_id), "notification_id")
        if (
            notice["status"] != "DRAFT"
            or notice["attempts"] != 0
            or notice["message_id"] is not None
            or digest(notice["message"]) != notice["message_sha256"]
        ):
            return self._block(
                "Outbox is not a fresh draft; uncertain delivery requires reconciliation",
                notice["status"] in {"UNKNOWN", "SENDING"},
            )
        self._update(self.identifier, status="NOTICE_PREPARED", active_stage=None)
        return self.inspect(self.identifier)

    def _audit_request(self, execution, experiment_id="circuit46_pulse_technical"):
        prefix = "Execution receipt: "
        if not execution["error"].startswith(prefix):
            raise ValueError("No coordinator-attested execution receipt")
        receipt_path = Path(execution["error"][len(prefix) :])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        root = Path(execution["root"])
        frozen = json.loads((root / "request.json").read_text(encoding="utf-8"))
        run_dir = Path(frozen["results"]) / experiment_id / receipt["run_id"]
        return AuditRequest(
            task_id=receipt["task_id"],
            candidate_id=receipt["candidate_id"],
            implementation_id=receipt["implementation_id"],
            execution_id=execution["execution_id"],
            experiment_id=experiment_id,
            run_id=receipt["run_id"],
            execution_receipt=str(receipt_path),
            execution_receipt_sha256=file_hash(receipt_path),
            resolved_configuration_sha256=file_hash(run_dir / "resolved.json"),
            dataset_manifest_sha256={
                d["dataset_id"]: d["manifest_sha256"] for d in frozen["plan"]["datasets"]
            },
        )
