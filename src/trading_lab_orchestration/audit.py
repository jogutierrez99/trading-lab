"""Manual deterministic audits, immutable dossiers and crash reconciliation."""

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from .audit_contracts import AuditRequest, AuditVerdict
from .audit_evidence import Evidence, review
from .contracts import canonical, digest
from .processes import coordinator_lock
from .store import utc_now
from .workspaces import file_hash, write_json


def report(verdict):
    o = verdict.observations
    lines = [
        "# Trading Lab: auditoría técnica 4.4",
        "",
        f"Auditoría: `{verdict.audit_id}`",
        f"Modo efectivo: {verdict.effective_review_mode}; "
        f"modelo ejecutado: {verdict.model_executed}.",
        f"Implementación: `{verdict.implementation_id}`; run: `{verdict.run_id}`.",
        f"Estado: {verdict.audit_status}; dictamen económico: {verdict.auditor_verdict}.",
        "",
        "**Prueba técnica. Sin validación económica ni elegibilidad para revisión demo/paper.**",
        f"Datos sintéticos: {o.get('synthetic', 'UNKNOWN')}; "
        f"runner: {o.get('runner_status', 'UNKNOWN')}.",
        "",
        "| Periodo | Versión | Operaciones | PF | Sharpe |",
        "|---|---|---:|---|---|",
    ]
    for item in o.get("native_results", []):
        m = item["result"]["metrics"]
        lines.append(
            f"| {m.get('period')} | {m.get('strategy_version')} | "
            f"{m.get('closed_trades')} | {m.get('profit_factor')} | {m.get('sharpe')} |"
        )
    lines += [
        "",
        (
            "Métricas null se conservan indefinidas; cero operaciones no "
            "rechaza económicamente la estrategia."
        ),
        "Etiquetas nativas íntegras en audit_verdict.json; PASS/FAIL no concede permisos.",
        "Historial de selección (hipótesis, distinto de las particiones sintéticas):",
        "```json",
        json.dumps(o.get("selection_history"), ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    if comparison := o.get("paired_comparison"):
        from .rmm_audit_summary import paired_report_lines

        lines += paired_report_lines(comparison)
    for key, gate in verdict.gates.items():
        lines += (
            [f"## Puerta {key}: {gate.status}"]
            + ["- " + x for x in gate.findings]
            + ["Referencias: " + ", ".join(gate.references), ""]
        )
    lines += ["## Bloqueos e incertidumbres"] + [
        "- " + x for x in verdict.blockers + verdict.uncertainties
    ]
    lines += [
        "",
        "Próxima comprobación mínima: " + verdict.recommended_next_test,
        "",
        "## Evidencia primaria",
        "Rutas locales; no enlaces públicos. El JSON contiene todos los hashes.",
    ]
    for key in (
        "execution_receipt",
        "execution_request",
        "implementation_receipt",
        "native:run.json",
        "native:summary.json",
        "native:ledger.sqlite",
        "native:resolved.json",
        "paired_comparison",
    ):
        if key in verdict.references:
            ref = verdict.references[key]
            lines += [f"- {key}: {ref.path}; SHA256 {ref.sha256}"]
    lines += [
        "",
        (
            "Auditoría de lectura: sin nuevas ejecuciones, edición de "
            "protocolos, activación, órdenes ni notificaciones por el auditor."
        ),
        "Coste API medido: desconocido/no aplicable sin llamada; no se confunde con reservas.",
        "",
    ]
    return "\n".join(lines)


class Auditor:
    def __init__(self, store):
        self.store = store
        self.lock = store.path.with_suffix(".audit.lock")

    def get(self, identifier):
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM audits WHERE audit_id=?", (identifier,)).fetchone()
        if not row:
            raise ValueError("Unknown audit identity")
        return dict(row)

    def inspect(self, identifier):
        row = self.get(identifier)
        root = Path(row["root"])
        if row["status"] != "PREPARED":
            if (
                canonical(json.loads((root / "audit_request.json").read_text(encoding="utf-8")))
                != row["request_json"]
            ):
                raise ValueError("Immutable audit request changed")
            for name, field in (
                ("audit_verdict.json", "verdict_sha256"),
                ("audit_report.md", "report_sha256"),
            ):
                if file_hash(root / name) != row[field]:
                    raise ValueError("Immutable audit artifact changed")
            row["verdict"] = json.loads((root / "audit_verdict.json").read_text(encoding="utf-8"))
        return row

    def run(self, request, artifacts):
        request = AuditRequest.model_validate_json(canonical(request.model_dump(mode="json")))
        if request.audit_id is not None:
            raise ValueError(
                "Coordinator assigns audit_id; use audit-reconcile for an existing audit"
            )
        if request.review_mode != "DETERMINISTIC_ONLY":
            raise ValueError(
                "MODEL_ASSISTED requires the explicit audit-openai command and "
                "a verified deterministic audit"
            )
        intent = digest(canonical(request.model_dump(mode="json")))
        with coordinator_lock(self.lock):
            with self.store.transaction() as conn:
                previous = conn.execute(
                    "SELECT audit_id FROM audits WHERE intent_sha256=?", (intent,)
                ).fetchone()
                if previous:
                    identifier = previous["audit_id"]
                else:
                    identifier = "audit_" + uuid4().hex
                    root = Path(artifacts).resolve() / identifier
                    execution = conn.execute(
                        "SELECT * FROM executions WHERE execution_id=?", (request.execution_id,)
                    ).fetchone()
                    if not execution:
                        raise ValueError("Unknown execution")
                    protected = [
                        Path(execution["root"]).resolve(),
                        self.store.path.parent,
                        Path(__file__).resolve().parents[2],
                    ]
                    source = conn.execute(
                        "SELECT root FROM attempts WHERE attempt_id=?", (execution["attempt_id"],)
                    ).fetchone()
                    protected.append(Path(source["root"]).resolve())
                    if execution["manual_repair_id"]:
                        repair = conn.execute(
                            "SELECT root FROM manual_repairs WHERE repair_id=?",
                            (execution["manual_repair_id"],),
                        ).fetchone()
                        protected.append(Path(repair["root"]).resolve())
                    control = Path(execution["root"]) / "request.json"
                    if (
                        control.exists()
                        and control.stat().st_size <= 1000000
                        and file_hash(control) == execution["request_sha256"]
                    ):
                        declared = json.loads(control.read_text(encoding="utf-8"))
                        protected += [
                            Path(d["path"]).resolve()
                            for d in declared["plan"]["datasets"]
                            if "path" in d
                        ]
                        protected += [Path(p).resolve().parent for p in declared["input_files"]]
                    if any(root.is_relative_to(p) or p.is_relative_to(root) for p in protected):
                        raise ValueError(
                            "Audit output must be separate from sources, repository and "
                            "coordinator database"
                        )
                    conn.execute(
                        (
                            "INSERT INTO audits(audit_id,execution_id,intent_sha256,reque"
                            "st_json,root,status,created_at_utc) VALUES(?,?,?,?,?,'PREPAR"
                            "ED',?)"
                        ),
                        (
                            identifier,
                            request.execution_id,
                            intent,
                            canonical(request.model_dump(mode="json") | {"audit_id": identifier}),
                            str(root),
                            utc_now(),
                        ),
                    )
            return self._complete(identifier)

    def reconcile(self, identifier):
        with coordinator_lock(self.lock):
            return self._complete(identifier)

    def _complete(self, identifier):
        row = self.get(identifier)
        if row["status"] != "PREPARED":
            return self.inspect(identifier)
        request = AuditRequest.model_validate_json(row["request_json"])
        if request.audit_id != identifier:
            raise ValueError("Audit request/registration identity mismatch")
        evidence = Evidence(request)
        blockers = []
        observations = {}
        try:
            observations = review(self.store, request, evidence)
            status, integrity = "COMPLETED_WITH_LIMITATIONS", "INTEGRITY_OK"
        except (ValueError, OSError, KeyError, TypeError, sqlite3.Error) as exc:
            # No raw file content, environment or transport exception is archived.
            blockers.append(
                "Primary evidence verification failed: "
                + type(exc).__name__
                + ": "
                + str(exc)[:500]
            )
            status, integrity = "BLOCKED_EVIDENCE", "INTEGRITY_FAIL"
        blockers += ["No independent economic validation; no demo/paper review eligibility."]
        if observations.get("synthetic"):
            blockers.append(
                "SYNTHETIC_TECHNICAL: fixture only; zero trades cannot support an "
                "economic decision."
            )
        gates = {
            "A": {
                "status": integrity,
                "findings": [
                    (
                        "Verified registered identities, receipts, controls, final "
                        "implementation, native ledger/results and artifact hashes."
                    )
                    if integrity == "INTEGRITY_OK"
                    else blockers[0]
                ],
                "references": list(evidence.refs)[:50],
            },
            "B": {
                "status": "DESIGN_LIMITED" if observations else "NOT_VERIFIABLE",
                "findings": [
                    (
                        "Archived native interface and test receipts are evidence of "
                        "specific checks, not a new causal audit."
                    ),
                    (
                        "Hypothesis selection history is preserved; consumed or unknown "
                        "holdout cannot establish independence."
                    ),
                ],
                "references": [
                    k
                    for k in ("implementation_receipt", "native:plan.json", "execution_request")
                    if k in evidence.refs
                ],
            },
            "C": {
                "status": "INSUFFICIENT_EVIDENCE",
                "findings": [
                    (
                        "Preserve native metrics, null values and denominators; synthetic "
                        "or insufficient evidence yields NO_DECISION."
                    ),
                    "No cost/parameter/regime/market robustness established by this audit.",
                ],
                "references": [
                    k
                    for k in ("native:summary.json", "native:metrics.csv", "native:leaderboard.csv")
                    if k in evidence.refs
                ],
            },
            "D": {
                "status": "NOT_READY",
                "findings": [
                    (
                        "Operational gap untested; no activation and no permission "
                        "inferred from a classification."
                    )
                ],
                "references": ["execution_receipt"] if "execution_receipt" in evidence.refs else [],
            },
        }
        verdict = AuditVerdict(
            audit_id=identifier,
            audit_task_id=identifier,
            **{
                k: getattr(request, k)
                for k in (
                    "task_id",
                    "candidate_id",
                    "implementation_id",
                    "execution_id",
                    "experiment_id",
                    "run_id",
                )
            },
            effective_review_mode="DETERMINISTIC_ONLY",
            audit_timestamp_utc=row["created_at_utc"],
            audit_status=status,
            gates=gates,
            auditor_verdict="NO_DECISION",
            original_classifications=observations.pop("original_classifications", []),
            observations=observations,
            references=evidence.refs,
            blockers=blockers,
            uncertainties=[
                (
                    "Global historical API spend and computing consumption are "
                    "unknown unless separately reconciled."
                ),
                (
                    "Scientific independence, statistical power and prospective "
                    "execution remain unverified."
                ),
            ],
            recommended_next_test=(
                "Review the preserved dossier and evidence gaps manually; "
                "predeclare genuinely independent evidence before any future "
                "authorized research."
            ),
            scope_of_verification=[
                "Bounded read-only file/hash/identity checks",
                "Native counts and results comparison; no new backtests or model calls",
            ],
        )
        root = Path(row["root"])
        root.mkdir(parents=True, exist_ok=True)
        for name, content in (
            ("audit_request.json", json.loads(row["request_json"])),
            ("audit_verdict.json", verdict.model_dump(mode="json")),
        ):
            path = root / name
            if path.exists():
                if json.loads(path.read_text(encoding="utf-8")) != content:
                    raise ValueError(
                        "Partial dossier differs; preserve it for manual investigation"
                    )
            else:
                write_json(path, content)
        output = root / "audit_report.md"
        text = report(verdict)
        if output.exists():
            if output.read_text(encoding="utf-8") != text:
                raise ValueError("Partial report differs; manual investigation required")
        else:
            with output.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        with self.store.transaction() as conn:
            conn.execute(
                (
                    "UPDATE audits SET status=?,verdict_sha256=?,report_sha256=? "
                    "WHERE audit_id=? AND status='PREPARED'"
                ),
                (status, file_hash(root / "audit_verdict.json"), file_hash(output), identifier),
            )
        return self.inspect(identifier)
