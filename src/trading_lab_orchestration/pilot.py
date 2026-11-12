"""Read-only reconstruction of a historical pilot. No run/send/reconcile operations."""

import sqlite3
from pathlib import Path
from uuid import uuid4

from .audit import Auditor
from .audit_contracts import AuditRequest, AuditVerdict
from .audit_evidence import Evidence, review
from .contracts import HypothesisManifest, canonical, digest
from .implementation_contracts import ImplementationRequest
from .pilot_contracts import PilotVerificationRequest, PilotVerificationResult, VerificationStage
from .readonly import ReadOnlyStore
from .store import utc_now
from .workspaces import file_hash, write_json

STAGES = ("intake", "implementation", "execution", "audit", "telegram")


class PilotVerifier:
    def __init__(self, database: Path):
        self.database = Path(database).resolve()

    def verify(self, request: PilotVerificationRequest) -> PilotVerificationResult:
        request = PilotVerificationRequest.model_validate_json(request.model_dump_json())
        self.request = request
        self.evidence = Evidence(request)
        self.state = None
        self.native = None
        self.audit = None
        self.protected_roots = {
            self.database.parent,
            Path(__file__).resolve().parents[2],
            Path(request.telegram_receipt).resolve().parent,
        }
        self.export_safe = True
        self.stages = {
            name: VerificationStage(identity=str(getattr(request, key)), status="NOT_CHECKED")
            for name, key in zip(
                STAGES,
                ("task_id", "implementation_id", "execution_id", "audit_id", "notification_id"),
                strict=True,
            )
        }
        database = {
            "path": str(self.database),
            "mode": "ro",
            "query_only": True,
            "migrations_performed": False,
        }
        try:
            self.evidence.file("pilot.database", self.database)
            with ReadOnlyStore(self.database).snapshot() as store:
                self.store = store
                self._collect_roots()
                self._stage("intake", self._intake)
                # The inherited 4.4 review verifies both implementation and native
                # execution. Its output, not status strings alone, supports closure.
                self._stage("execution", self._execution)
                self._stage("implementation", self._implementation)
                self._stage("audit", self._audit)
                self._stage("telegram", self._telegram)
                self.evidence.recheck()
            database["sha256"] = self.evidence.refs["pilot.database"]["sha256"]
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            self.stages["intake"] = self._failure(request.task_id, exc)
        passed = all(s.status == "VERIFIED" for s in self.stages.values())
        observations = {}
        if self.native:
            observations = {
                key: self.native[key]
                for key in (
                    "summary",
                    "protocol",
                    "protocol_sha256",
                    "scope",
                    "synthetic",
                    "dataset_identity",
                    "base_commit",
                    "final_files",
                    "implementation_origin",
                    "implementation_provenance",
                    "selection_history",
                    "search_history",
                    "model_development_attempts",
                    "original_classifications",
                    "hypothesis_manifest_sha256",
                )
            }
            observations["cases"] = [
                item["result"]["metrics"] for item in self.native["native_results"]
            ]
        return PilotVerificationResult(
            verification_id="verification_" + uuid4().hex,
            verified_at_utc=utc_now(),
            status=("VERIFIED_HISTORICAL_TECHNICAL_PILOT" if passed else "BLOCKED"),
            request=request,
            candidate_id=self.state["candidate_id"] if self.state else None,
            hypothesis_id=self.state["hypothesis_id"] if self.state else None,
            experiment_id=self.audit["verdict"]["experiment_id"] if self.audit else None,
            database=database,
            protected_roots=sorted(str(p) for p in self.protected_roots),
            export_safe=self.export_safe,
            stages=self.stages,
            references=self.evidence.refs,
            observations=observations,
            limitations=[
                "A: Verification of a historical trajectory; per-stage findings determine closure.",
                "Historical manual format and semantic repairs prevent an unattended claim.",
                "B: Recovery tests use isolated simulated components; not new real incidents.",
                "C: No new end-to-end execution, Codex invocation, backtest or network call.",
                "D: Real AI auditor integration and acceptance remain pending.",
                "E: Synthetic evidence provides no economic validation or demo authorization.",
                "Telegram acceptance is checked from local pinned evidence, not a new API query.",
            ],
            actions_pending=[
                "Do not advance to step5 or activate demo automatically.",
                "MODEL_ASSISTED requires an explicit connector and reconciled global "
                "API accounting.",
            ]
            + (
                []
                if passed
                else [
                    "Resolve the reported evidence gaps/contradictions separately; "
                    "no automatic relaunch."
                ]
            ),
        )

    @staticmethod
    def _failure(identity, exc):
        return VerificationStage(
            identity=identity,
            status="MISSING_EVIDENCE" if isinstance(exc, OSError) else "CONTRADICTION",
            evidence=[type(exc).__name__ + ": " + str(exc)[:600]],
        )

    def _collect_roots(self):
        # Protect source directories even if later evidence verification fails.
        with self.store.connection() as c:
            for table in ("attempts", "executions", "manual_repairs"):
                for row in c.execute(
                    "SELECT root FROM " + table + " WHERE task_id=?", (self.request.task_id,)
                ):
                    self.protected_roots.add(Path(row["root"]).resolve())
            for row in c.execute(
                "SELECT root FROM audits WHERE audit_id=?", (self.request.audit_id,)
            ):
                self.protected_roots.add(Path(row["root"]).resolve())
            execution = c.execute(
                "SELECT root FROM executions WHERE execution_id=?", (self.request.execution_id,)
            ).fetchone()
        if execution:
            self.protected_roots.add(Path(execution["root"]).resolve())
            path = Path(execution["root"]) / "request.json"
            try:
                data = self.evidence.json("pilot.execution_paths", path)
                for dataset in data["plan"]["datasets"]:
                    if "path" in dataset:
                        self.protected_roots.add(Path(dataset["path"]).resolve())
                for filename in data["input_files"]:
                    self.protected_roots.add(Path(filename).resolve().parent)
            except (OSError, ValueError, KeyError, TypeError):
                self.export_safe = False  # stdout remains available; never guess safe output roots.

    def _stage(self, name, function):
        try:
            self.stages[name] = function()
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            self.stages[name] = self._failure(self.stages[name].identity, exc)

    def _intake(self):
        r = self.request
        state = self.store.show(r.task_id)
        manifest = HypothesisManifest.model_validate_json(canonical(state["manifest"]))
        if (
            state["task"]["task_id"] != r.task_id
            or manifest.hypothesis_id != state["hypothesis_id"]
            or state["task"]["kind"] != "IMPLEMENTATION"
            or state["task"]["candidate_id"] != state["candidate_id"]
            or digest(manifest.snapshot()) != state["manifest_sha256"]
            or manifest.fingerprint() != state["fingerprint"]
        ):
            raise ValueError("Manifest/candidate/task identity or fingerprint mismatch")
        if state["task"]["status"] != "SUCCEEDED" or state["status"] != "IMPLEMENTATION_READY":
            raise ValueError("Task/candidate are not implemented and verified")
        for submission in state["submissions"]:
            submitted = HypothesisManifest.model_validate_json(submission["manifest_json"])
            if (
                submission["candidate_id"] != state["candidate_id"]
                or submitted.hypothesis_id != submission["hypothesis_id"]
                or digest(submission["manifest_json"]) != submission["manifest_sha256"]
                or submitted.fingerprint() != state["fingerprint"]
            ):
                raise ValueError("Submission lineage mismatch")
        if not state["submissions"]:
            raise ValueError("No registered submission")
        for event in state["events"]:
            if (
                event["candidate_id"] != state["candidate_id"]
                or event["task_id"] not in (None, r.task_id)
                or digest(event["payload_json"]) != event["payload_sha256"]
            ):
                raise ValueError("Event lineage/hash mismatch")
        for entity, expected in (("task", "SUCCEEDED"), ("candidate", "IMPLEMENTATION_READY")):
            events = [e for e in state["events"] if e["entity"] == entity]
            if not events or events[-1]["new_state"] != expected:
                raise ValueError("Event history does not support final " + entity + " state")
        attempts = state["attempts"]
        if [a["number"] for a in attempts] != [1, 2, 3] or any(
            a["task_id"] != r.task_id for a in attempts
        ):
            raise ValueError("Expected exact exhausted implementation budget3/3")
        if attempts[-1]["status"] != "SUCCEEDED":
            raise ValueError("Last implementation source did not succeed")
        for attempt in attempts:
            if not attempt["request_sha256"]:
                raise ValueError("Missing pinned implementation attempt request digest")
            if attempt["status"] in {"PREPARED", "RUNNING", "UNKNOWN"}:
                raise ValueError("Implementation source is active/uncertain; no automatic relaunch")
            path = self.evidence.file(
                "pilot.attempt:" + attempt["attempt_id"],
                Path(attempt["root"]) / "request.json",
                attempt["request_sha256"],
            )
            source = ImplementationRequest.model_validate_json(path.read_text(encoding="utf-8"))
            if (
                source.task_id != r.task_id
                or source.candidate_id != state["candidate_id"]
                or source.attempt_id != attempt["attempt_id"]
                or source.attempt_number != attempt["number"]
                or source.hypothesis_sha256 != state["manifest_sha256"]
                or source.hypothesis_manifest.snapshot() != manifest.snapshot()
            ):
                raise ValueError("Attempt request is not bound to the registered hypothesis/task")
        self.state = state
        return VerificationStage(
            identity=r.task_id,
            historical_state="SUCCEEDED",
            status="VERIFIED",
            evidence=[
                "pilot.database: validated HypothesisManifest, fingerprint, submissions and events",
                "candidate_id=" + state["candidate_id"],
                "Implementation attempts3/3 consumed",
            ],
            manual_intervention=["Manual hypothesis intake and reviewed development request"],
            limitations=["HYPOTHESIS_READY and implementation success are not economic approval"],
        )

    def _load_audit(self):
        if self.audit is not None:
            return self.audit
        row = Auditor(self.store).get(self.request.audit_id)
        if row["status"] != "COMPLETED_WITH_LIMITATIONS":
            raise ValueError("Historical audit is not completed with limitations")
        root = Path(row["root"])
        self.evidence.file(
            "pilot.audit_verdict", root / "audit_verdict.json", row["verdict_sha256"]
        )
        self.evidence.file("pilot.audit_report", root / "audit_report.md", row["report_sha256"])
        self.evidence.file("pilot.audit_request", root / "audit_request.json")
        audit = Auditor(self.store).inspect(self.request.audit_id)
        v = AuditVerdict.model_validate(audit["verdict"])
        if (
            audit["execution_id"] != self.request.execution_id
            or v.audit_id != self.request.audit_id
            or v.task_id != self.request.task_id
            or v.implementation_id != self.request.implementation_id
            or v.execution_id != self.request.execution_id
            or v.run_id != self.request.run_id
        ):
            raise ValueError("Audit/requested trajectory identity mismatch")
        if (
            v.effective_review_mode != "DETERMINISTIC_ONLY"
            or v.model_executed
            or v.auditor_verdict != "NO_DECISION"
            or v.economic_validation
            or v.human_paper_review_eligible
        ):
            raise ValueError("Frozen audit contradicts the declared technical-only pilot")
        if v.audit_task_id != self.request.audit_id or tuple(v.gates[k].status for k in "ABCD") != (
            "INTEGRITY_OK",
            "DESIGN_LIMITED",
            "INSUFFICIENT_EVIDENCE",
            "NOT_READY",
        ):
            raise ValueError("Frozen audit gates/task do not support this technical closure")
        self.audit = audit
        return audit

    def _execution(self):
        r = self.request
        with self.store.connection() as c:
            row = c.execute(
                "SELECT * FROM executions WHERE execution_id=?", (r.execution_id,)
            ).fetchone()
        if not row:
            raise FileNotFoundError("Execution not registered")
        if row["status"] != "SUCCEEDED":
            raise ValueError(
                "Execution "
                + row["status"]
                + "; reconcile uncertainty separately; never relaunch here"
            )
        if (
            row["task_id"] != r.task_id
            or (row["manual_repair_id"] or row["attempt_id"]) != r.implementation_id
        ):
            raise ValueError("Execution/implementation/task relationship mismatch")
        audit = self._load_audit()
        audit_request = AuditRequest.model_validate_json(audit["request_json"])
        if audit_request.review_mode != "DETERMINISTIC_ONLY":
            raise ValueError("Historical request does not declare deterministic review")
        for name in ("task_id", "implementation_id", "execution_id", "run_id", "audit_id"):
            if getattr(audit_request, name) != getattr(r, name):
                raise ValueError("Frozen audit request identifies a different trajectory: " + name)
        if audit_request.experiment_id != audit["verdict"]["experiment_id"]:
            raise ValueError("Frozen audit experiment identity mismatch")
        if self.state is None or audit_request.candidate_id != self.state["candidate_id"]:
            raise ValueError("Audit candidate is not the verified intake candidate")
        native = review(self.store, audit_request, self.evidence)
        if not native["synthetic"] or native["scope"] != "SYNTHETIC_TECHNICAL":
            raise ValueError("This pilot requires explicit synthetic technical provenance")
        if native["summary"]["total_backtests"] != r.expected_backtests:
            raise ValueError("Unexpected backtest count")
        for item in native["native_results"]:
            m = item["result"]["metrics"]
            if (
                m["strategy"] != r.strategy
                or m["strategy_version"] != r.strategy_version
                or m["closed_trades"] != r.expected_closed_trades_per_case
            ):
                raise ValueError("Native strategy/version/sample mismatch")
        if native["hypothesis_manifest_sha256"] != self.state["manifest_sha256"]:
            raise ValueError("Execution is not bound to the intake hypothesis")
        self.native = native
        self.execution = dict(row)
        return VerificationStage(
            identity=r.execution_id + " / " + r.run_id,
            historical_state="SUCCEEDED / COMPLETE",
            status="VERIFIED",
            evidence=[
                "execution_receipt",
                "native:run.json",
                "native:ledger.sqlite",
                "native:summary.json",
                "native:metrics.csv",
                "Native completed cases="
                + str(len(native["native_results"]))
                + "; closed_trades_per_case="
                + canonical(
                    [
                        item["result"]["metrics"]["closed_trades"]
                        for item in native["native_results"]
                    ]
                )
                + "; filter_rejected="
                + str(native["summary"]["filter_rejected_backtests"]),
            ],
            manual_intervention=["Explicit manual execution with bounded synthetic plan"],
            limitations=[
                "Complete technical execution; native filter rejections preserved",
                "Synthetic TRAIN/validation/test are not historical independent holdouts",
            ],
        )

    def _implementation(self):
        r = self.request
        if self.native is None:
            return VerificationStage(
                identity=r.implementation_id,
                status="NOT_CHECKED",
                limitations=["Inherited implementation/execution proof did not complete"],
            )
        path = self.evidence.refs["source_tree:request.json"]["path"]
        source = ImplementationRequest.model_validate_json(Path(path).read_text(encoding="utf-8"))
        if (
            source.task_id != r.task_id
            or source.candidate_id != self.state["candidate_id"]
            or source.hypothesis_sha256 != self.state["manifest_sha256"]
            or source.hypothesis_manifest.snapshot() != canonical(self.state["manifest"])
            or source.attempt_id != self.execution["attempt_id"]
            or source.attempt_id != self.state["attempts"][-1]["attempt_id"]
        ):
            raise ValueError(
                "Original implementation request does not bind the same hypothesis/source"
            )
        origin = self.native["implementation_origin"]
        provenance = self.native["implementation_provenance"]
        interventions = []
        if origin == "MANUAL_TECHNICAL_REPAIR":
            if (
                provenance["source_attempt_id"] != source.attempt_id
                or not provenance["source_operator_format_repair"]
                or not provenance["author"]
                or provenance["model_invocations"] != 0
            ):
                raise ValueError("Manual repair provenance or inherited format repair missing")
            interventions = [
                "Operator-authorized format repair (AST unchanged)",
                "Manual semantic compatibility repair with new identity and final hashes",
            ]
        elif provenance.get("operator_format_repair"):
            interventions = ["Operator-authorized format repair"]
        return VerificationStage(
            identity=r.implementation_id,
            historical_state="IMPLEMENTED_VERIFIED",
            status="VERIFIED",
            evidence=[
                "implementation_receipt",
                "source_tree:request.json",
                "Final hashes: " + canonical(self.native["final_files"]),
            ],
            manual_intervention=interventions,
            limitations=[
                "Budget remains3/3; no fourth model invocation",
                "Not unattended automation",
            ],
        )

    def _audit(self):
        r = self.request
        audit = self._load_audit()
        if self.native is None:
            return VerificationStage(
                identity=r.audit_id,
                status="NOT_CHECKED",
                limitations=[
                    "Frozen report exists; underlying current proof could not be established"
                ],
            )
        v = AuditVerdict.model_validate(audit["verdict"])
        if v.candidate_id != self.state["candidate_id"]:
            raise ValueError("Audit candidate mismatch")
        for key, ref in v.references.items():
            current = self.evidence.refs.get(key)
            if current != ref.model_dump():
                raise ValueError(
                    "Frozen audit reference no longer matches verified evidence: " + key
                )
        expected = {k: value for k, value in self.native.items() if k != "original_classifications"}
        if (
            v.observations != expected
            or v.original_classifications != self.native["original_classifications"]
        ):
            raise ValueError("Frozen audit observations contradict native evidence")
        return VerificationStage(
            identity=r.audit_id,
            historical_state=v.audit_status,
            status="VERIFIED",
            evidence=["pilot.audit_request", "pilot.audit_verdict", "pilot.audit_report"],
            limitations=["DETERMINISTIC_ONLY / NO_DECISION; real AI auditor not deployed"],
        )

    def _telegram(self):
        r = self.request
        with self.store.connection() as c:
            row = c.execute(
                "SELECT * FROM audit_outbox WHERE notification_id=?", (r.notification_id,)
            ).fetchone()
        if not row:
            raise FileNotFoundError("Notification not registered")
        if row["status"] in {"UNKNOWN", "SENDING"}:
            raise ValueError(
                "Telegram " + row["status"] + "; explicit reconciliation required, no resend"
            )
        if (
            row["status"] != "ACCEPTED"
            or row["audit_id"] != r.audit_id
            or row["event"] != "AUDIT_TECHNICAL_NOTICE"
            or not row["recipient_sha256"]
            or row["attempts"] != r.expected_send_attempts
            or row["message_id"] != r.expected_message_id
            or digest(row["message"]) != row["message_sha256"]
        ):
            raise ValueError("Outbox identity/state/message proof mismatch")
        receipt = self.evidence.json(
            "pilot.telegram_receipt", r.telegram_receipt, r.telegram_receipt_sha256
        )
        for key, expected in {
            "schema_version": "1.0",
            "kind": "ManualTelegramAcceptance",
            "audit_id": r.audit_id,
            "notification_id": r.notification_id,
            "status": "ACCEPTED",
            "attempts": row["attempts"],
            "message_id": row["message_id"],
            "outcome": row["outcome"],
            "message_sha256": row["message_sha256"],
            "private_chat_verified": True,
            "service_acceptance_is_not_read_receipt": True,
        }.items():
            if receipt.get(key) != expected:
                raise ValueError("Telegram receipt/outbox mismatch: " + key)
        if row["outcome"] != "TELEGRAM_SERVICE_ACCEPTED" or self.audit is None:
            raise ValueError("No matching frozen audit or service acceptance")
        for identity in (
            r.audit_id,
            r.run_id,
            r.strategy,
            r.strategy_version,
            self.audit["report_sha256"],
            "NO_DECISION",
        ):
            if identity not in row["message"]:
                raise ValueError("Notification text does not identify the audited dossier")
        return VerificationStage(
            identity=r.notification_id,
            historical_state="ACCEPTED",
            status="VERIFIED",
            evidence=[
                "pilot.database",
                "pilot.telegram_receipt",
                "message_id=" + str(row["message_id"]) + "; attempts=" + str(row["attempts"]),
            ],
            manual_intervention=[
                "Explicit user-authorized real send using existing configured private chat"
            ],
            limitations=[
                "Local pinned service receipt; no new Telegram query or send",
                "Acceptance is not a read receipt",
            ],
        )


def render_pilot(result: PilotVerificationResult) -> str:
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = [
        "# Trading Lab: cierre del piloto histórico4.5",
        "",
        result.status,
        "",
        "Verificación: " + result.verification_id,
        "Fecha UTC: " + result.verified_at_utc,
        "Candidata: " + str(result.candidate_id),
        "Ficha: " + str(result.hypothesis_id),
        "",
        "| Etapa | Identidad | Estado histórico / verificación | Evidencia | "
        "Intervención manual | Limitaciones |",
        "|---|---|---|---|---|---|",
    ]
    for name, stage in result.stages.items():
        lines.append(
            "| "
            + " | ".join(
                cell(v)
                for v in (
                    name,
                    stage.identity,
                    str(stage.historical_state) + " / " + stage.status,
                    "; ".join(stage.evidence),
                    "; ".join(stage.manual_intervention),
                    "; ".join(stage.limitations),
                )
            )
            + " |"
        )
    lines += ["", "## Alcance y limitaciones"] + ["- " + t for t in result.limitations]
    lines += ["", "## Acciones pendientes"] + ["- " + t for t in result.actions_pending]
    lines += [
        "",
        "El JSON adjunto conserva referencias/hashes y métricas/clasificaciones nativas.",
        "No se ha realizado una nueva ejecución completa ni validación económica/demo.",
        "",
    ]
    return "\n".join(lines)


def export_pilot(result: PilotVerificationResult, destination: Path) -> dict:
    if not result.export_safe:
        raise ValueError(
            "Incomplete path controls prevent safe export; use stdout without --output"
        )
    root = Path(destination).resolve() / result.verification_id
    protected = [Path(result.database["path"]).parent, Path(__file__).resolve().parents[2]]
    protected += [Path(ref.path).resolve().parent for ref in result.references.values()]
    protected += [Path(p) for p in result.protected_roots]
    if any(root.is_relative_to(p) for p in protected):
        raise ValueError("Export must be outside inspected evidence, database and repository")
    root.mkdir(parents=True, exist_ok=False)
    write_json(root / "pilot_verification.json", result.model_dump(mode="json"))
    with (root / "pilot_report.md").open("x", encoding="utf-8", newline="\n") as f:
        f.write(render_pilot(result))
    hashes = {p.name: file_hash(p) for p in root.iterdir()}
    write_json(root / "hashes.json", hashes)
    return {"directory": str(root), "sha256": hashes}
