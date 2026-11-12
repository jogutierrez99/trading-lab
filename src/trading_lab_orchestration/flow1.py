"""Bind a single frozen research intake and finish its draft after the paid audit."""

import json
from pathlib import Path

from .audit_model import validate_model_review
from .audit_openai import verified_source
from .billing import reconcile
from .circuit import FLOW1_PAUSE, CircuitRunner
from .circuit_contracts import FLOW1_ID, TARGET, CircuitRequest
from .contracts import HypothesisManifest, canonical, digest
from .implementation_contracts import ImplementationPlan
from .processes import coordinator_lock
from .store import Store
from .workspaces import file_hash, write_json


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _call(budget, purpose):
    rows = [row for row in budget.inspect()["calls"] if row["purpose"] == purpose]
    if len(rows) != 1 or rows[0]["provider"] != "openai":
        raise ValueError("Flow 1 requires one matching OpenAI ledger call")
    row = rows[0]
    proof = json.loads(row["provenance"] or "null")
    if row["status"] == "SETTLED":
        proof = json.loads(proof["prior_calculation"])
    if not isinstance(proof, dict):
        raise ValueError("Flow 1 requires verified provider provenance")
    return row, proof


def research_request(store, budget, dossier):
    if store.path == budget.store.path:
        raise ValueError("Flow 1 requires a database separate from the global ledger")
    dossier = Path(dossier).resolve()
    result = _read(dossier / "result.json")
    intent = _read(dossier / "intent.json")
    source_sha = file_hash(dossier / "source.json")
    if result["status"] != "REGISTERED" or not result["task_id"]:
        raise ValueError("Flow 1 requires an accepted research intake")
    task = store.show(result["task_id"])
    manifest = HypothesisManifest.model_validate_json(canonical(task["manifest"]))
    row, proof = _call(budget, "openai-research-v1:" + source_sha)
    if (
        result["batch_sha256"] != source_sha
        or intent["source_sha256"] != source_sha
        or Path(intent["queue_db"]).resolve() != store.path
        or Path(proof["dossier"]).resolve() != dossier
        or row["call_id"] != intent["call_id"]
        or row["call_id"] != result["call_id"]
        or row["status"] not in {"UNKNOWN", "SETTLED"}
        or proof["status"] != "SELECTION_RECORDED"
        or proof["provider_receipt_sha256"] != file_hash(dossier / "provider-receipt.json")
        or task["candidate_id"] != result["candidate_id"]
        or manifest.hypothesis_id != "research_" + source_sha
        or digest(manifest.snapshot()) != result["manifest_sha256"]
        or file_hash(dossier / "manifest.json") != result["manifest_sha256"]
    ):
        raise ValueError("Flow 1 intake identity or evidence differs from the ledger")
    return CircuitRequest(
        circuit_id=FLOW1_ID,
        manifest=manifest,
        implementation=ImplementationPlan(
            schema_version="1.0",
            operation="NEW_STRATEGY",
            target=TARGET,
            specification_reviewed=True,
            review_note="Frozen synthetic Flow 1 acceptance only",
            max_wall_seconds=300,
            check_timeout_seconds=45,
        ),
    ), row


def draft(store, budget, research_dossier, model_dossier):
    runner = CircuitRunner(store)
    with coordinator_lock(runner.lock):
        request, research = research_request(store, budget, research_dossier)
        row = runner.inspect(request.circuit_id)
        if (
            row["request_sha256"] != digest(canonical(request.model_dump(mode="json")))
            or research["status"] != "SETTLED"
            or not row["audit_id"]
            or (row["error"] != FLOW1_PAUSE and row["status"] != "NOTICE_PREPARED")
        ):
            raise ValueError("Flow 1 requires its saved deterministic audit and settled research")
        original, audit_request, _, packet = verified_source(store, row["audit_id"])
        model_dossier = Path(model_dossier).resolve()
        model_call, proof = _call(budget, "openai-audit-v1:" + audit_request.execution_id)
        receipt_path = model_dossier / "review_receipt.json"
        receipt_sha = file_hash(receipt_path)
        receipt = _read(receipt_path)
        if (
            receipt_sha != proof["review_receipt_sha256"]
            or receipt["status"] != "COMPLETED"
            or receipt["call_id"] != model_call["call_id"]
            or receipt["origin_audit_id"] != row["audit_id"]
            or receipt["origin_execution_id"] != row["execution_id"]
            or receipt["origin_verdict_sha256"] != original["verdict_sha256"]
            or receipt["run_id"] != audit_request.run_id
            or canonical(receipt["evidence_packet"]) != canonical(packet)
        ):
            raise ValueError("Flow 1 requires the matching completed OpenAI audit receipt")
        validate_model_review(canonical(receipt["review"]), packet["references"])
        if row["status"] == "NOTICE_PREPARED":
            return row
        notice = runner.outbox.preview(row["audit_id"])
        if notice["status"] != "DRAFT" or notice["attempts"] or notice["message_id"] is not None:
            raise ValueError("Flow 1 requires an unsent draft")
        pointer = {
            "call_id": model_call["call_id"],
            "receipt": str(receipt_path),
            "sha256": receipt_sha,
        }
        path = Path(row["root"]) / "flow1-model-audit.json"
        if path.exists():
            if _read(path) != pointer:
                raise ValueError("Flow 1 model audit checkpoint differs")
        else:
            write_json(path, pointer)
        evidence = json.loads(row["evidence_json"])
        evidence[path.name] = file_hash(path)
        runner._update(
            request.circuit_id,
            status="NOTICE_PREPARED",
            active_stage=None,
            error=None,
            notification_id=notice["notification_id"],
            evidence_json=canonical(evidence),
        )
        return runner.inspect(request.circuit_id)


def billing_cycle(store, budget, research_dossier, model_dossier, call_id, project):
    """One poll and local handoff. It never starts an implementation, model or runner."""
    request, research = research_request(store, budget, research_dossier)
    row = CircuitRunner(store).inspect(request.circuit_id)
    if (
        row["status"] not in {"AWAITING_MODEL_AUDIT", "NOTICE_PREPARED"}
        or not row["audit_id"]
        or not row["execution_id"]
        or row["request_sha256"] != digest(canonical(request.model_dump(mode="json")))
    ):
        raise ValueError("Flow 1 requires the saved deterministic audit before the billing cycle")
    purpose = "openai-audit-v1:" + row["execution_id"]
    if call_id != research["call_id"]:
        audit, proof = _call(budget, purpose)
        path = Path(model_dossier).resolve() / "review_receipt.json"
        if call_id != audit["call_id"] or research["status"] != "SETTLED":
            raise ValueError("Call is not the auditor of this settled Flow 1 intake")
        if not path.is_file() or file_hash(path) != proof.get("review_receipt_sha256"):
            raise ValueError("Flow 1 auditor receipt is absent or differs from the ledger")
        receipt = _read(path)
        if receipt["call_id"] != call_id or receipt["origin_audit_id"] != row["audit_id"]:
            raise ValueError("Flow 1 auditor receipt belongs to another call or audit")

    billing = reconcile(budget, call_id, project=project, admin=True, apply=True, snapshots=True)
    result = {
        "circuit_id": request.circuit_id,
        "circuit_status": row["status"],
        "task_id": row["task_id"],
        "execution_id": row["execution_id"],
        "audit_id": row["audit_id"],
        "notification_id": row["notification_id"],
        "billing": billing,
    }
    if billing["ledger_status"] != "SETTLED":
        return result | {"status": "WAITING_BILLING"}
    if row["status"] == "NOTICE_PREPARED":
        return result | {"status": "NOTICE_PREPARED"}
    if call_id == research["call_id"]:
        existing = any(entry["purpose"] == purpose for entry in budget.inspect()["calls"])
        if existing:
            return result | {"status": "AUDITOR_ALREADY_RESERVED"}
        if billing["budget_blocker"]:
            return result | {"status": "WAITING_GLOBAL_LEDGER"}
        return result | {"status": "READY_FOR_AUDITOR_PREFLIGHT"}
    if receipt["status"] != "COMPLETED":
        return result | {"status": "AUDITOR_REVIEW_INCOMPLETE"}
    completed = draft(Store(store.path), budget, research_dossier, model_dossier)
    return result | {
        "status": completed["status"],
        "circuit_status": completed["status"],
        "notification_id": completed["notification_id"],
    }
