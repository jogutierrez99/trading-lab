"""Read-only review of a sealed GitHub intake and a prospective local approval."""

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError, field_validator

from .audit_model import MONTHLY_CAP_CENTS, Budget
from .contracts import HypothesisManifest, Identifier, Model, Period, Text, canonical, digest
from .github_intake import REPO, Proposal
from .implementation import check_spec_fields, review_runner
from .implementation_contracts import (
    PILOT_PREPARATION_BLOCKED,
    TECHNICAL_PILOT_ORIGIN,
    Hash,
    ImplementationPlan,
)
from .readonly import ReadOnlyStore

DEFAULT_AUTHOR_ID = 64194024


class ReviewAuthorization(Model):
    schema_version: Literal["1.0"]
    repository: Literal["jogutierrez99/trading-lab"]
    issue_number: int
    issue_id: int
    task_id: Identifier
    proposal_sha256: Hash
    plan_sha256: Hash
    permission: Literal["PREPARE_ONLY"]
    operation: Literal["NEW_STRATEGY", "NEW_EXPERIMENT"]
    approved_by: Text
    approved_at_utc: datetime

    _utc = field_validator("approved_at_utc")(Period.utc.__func__)


def _proposal(conn, row, task_id, author_id):
    if (
        row["source_mode"] != "GITHUB"
        or row["issue_url"] != f"https://github.com/{REPO}/issues/{row['issue_number']}"
        or row["issue_number"] <= 0
        or row["issue_id"] <= 0
        or row["author_id"] != author_id
        or not row["body_sha256"]
        or not re.fullmatch(r"[0-9a-f]{64}", row["body_sha256"])
    ):
        raise ValueError("INVALID_GITHUB_PROVENANCE")
    if not row["proposal_json"] or digest(row["proposal_json"]) != row["proposal_sha256"]:
        raise ValueError("PROPOSAL_HASH_MISMATCH")
    proposal = Proposal.model_validate_json(row["proposal_json"])
    manifest = proposal.manifest
    if (
        canonical(proposal.model_dump(mode="json")) != row["proposal_json"]
        or proposal.identity() != row["identity"]
        or proposal.research_date.isoformat() != row["research_date"]
    ):
        raise ValueError("PROPOSAL_METADATA_MISMATCH")
    task = conn.execute(
        """SELECT t.task_id,t.candidate_id,t.kind,t.mode,t.status,c.status AS candidate_status,
                  c.manifest_json,c.manifest_sha256,c.fingerprint,
                  s.manifest_json AS submission_json,s.manifest_sha256 AS submission_sha256
           FROM submissions s JOIN candidates c USING(candidate_id)
           JOIN tasks t USING(candidate_id) WHERE s.hypothesis_id=?""",
        (manifest.hypothesis_id,),
    ).fetchone()
    snapshot = manifest.snapshot()
    if (
        not task
        or task["task_id"] != row["task_id"]
        or (task_id is not None and task_id != task["task_id"])
    ):
        raise ValueError("TASK_BINDING_MISMATCH")
    if (
        task["manifest_json"] != snapshot
        or task["submission_json"] != snapshot
        or task["manifest_sha256"] != digest(snapshot)
        or task["submission_sha256"] != task["manifest_sha256"]
        or task["fingerprint"] != manifest.fingerprint()
    ):
        raise ValueError("MANIFEST_BINDING_MISMATCH")
    return proposal, task


def _technical(manifest: HypothesisManifest):
    data, execution = manifest.data_requirements, manifest.execution_assumptions
    missing = []
    protocols = []
    try:
        check_spec_fields(manifest)
    except ValueError as exc:
        missing.append(str(exc))
    try:
        runner = review_runner(manifest)
    except ValueError as exc:
        protocols.append(str(exc))
        runner = None
    if len(data.assets) > 1:
        protocols.append(
            "Review a dedicated protocol for synchronized legs, portfolio valuation "
            "and shared risk. The current preparation path does not verify joint execution."
        )
    if data.availability != "MANUALLY_VERIFIED":
        missing.append("Verify dataset coverage, aligned bars and warmup in every partition")
    if manifest.evaluation_plan.holdout_status != "UNOBSERVED_DECLARED":
        missing.append("Review holdout provenance and identify an independent evaluation window")
    if protocols:
        status = "REQUIRES_TECHNICAL_PROTOCOL"
    elif missing:
        status = "INSUFFICIENT_INFORMATION"
    else:
        status = "COMPATIBLE_FOR_REVIEW"
    return {
        "status": status,
        "protocol_blockers": protocols,
        "requirements": missing,
        "runner": runner if not protocols else None,
        "market": execution.market_mode,
        "assets": data.assets,
        "timeframe": data.timeframe,
        "data_availability": data.availability,
        "dataset_refs": data.dataset_refs,
        "warmup_bars": data.warmup_bars,
        "gap_policy": data.gap_policy,
        "funding_policy": data.funding_policy,
        "holdout": manifest.evaluation_plan.holdout_status,
        "evaluation_plan": manifest.evaluation_plan.model_dump(mode="json"),
        "signals": manifest.signal_spec.model_dump(mode="json"),
        "parameters": manifest.parameter_space.model_dump(mode="json"),
        "execution_assumptions": execution.model_dump(mode="json"),
        "expected_operation": "NEW_STRATEGY"
        if manifest.requires_new_strategy_code
        else "NEW_EXPERIMENT",
    }


def _work_blockers(conn, task):
    blockers = []
    if (task["kind"], task["mode"], task["status"], task["candidate_status"]) != (
        "MANUAL_REVIEW",
        "PREPARE_ONLY",
        "QUEUED",
        "HYPOTHESIS_READY",
    ):
        blockers.append("TASK_NOT_IN_MANUAL_REVIEW")
    prior = conn.execute(
        "SELECT number FROM attempts WHERE task_id=? ORDER BY number DESC LIMIT 1",
        (task["task_id"],),
    ).fetchone()
    if prior:
        blockers.append(
            "ATTEMPT_LIMIT_REACHED" if prior["number"] >= 3 else "REVIEW_EXISTING_ATTEMPT"
        )
    for table, active in (
        ("attempts", "('PREPARED','RUNNING','UNKNOWN')"),
        ("executions", "('PREPARED','RUNNING','UNKNOWN')"),
        ("manual_repairs", "('RUNNING','UNKNOWN')"),
    ):
        if conn.execute(f"SELECT 1 FROM {table} WHERE status IN {active} LIMIT 1").fetchone():
            blockers.append("ACTIVE_OR_UNCERTAIN_" + table.upper())
    return blockers


def _check_authorization(approval, plan, row, manifest):
    if plan is None:
        return "PLAN_REQUIRED"
    if plan.operation != (
        "NEW_STRATEGY" if manifest.requires_new_strategy_code else "NEW_EXPERIMENT"
    ):
        return "PLAN_OPERATION_MISMATCH"
    if approval is None:
        return "AUTHORIZATION_REQUIRED"
    plan_sha = digest(canonical(plan.model_dump(mode="json")))
    if (
        approval.issue_number != row["issue_number"]
        or approval.issue_id != row["issue_id"]
        or approval.task_id != row["task_id"]
        or approval.proposal_sha256 != row["proposal_sha256"]
        or approval.plan_sha256 != plan_sha
        or approval.operation != plan.operation
        or approval.approved_at_utc > datetime.now(UTC)
    ):
        return "AUTHORIZATION_BINDING_MISMATCH"
    return "BINDING_VALID"


def diagnose_issue(
    database: Path,
    issue: int,
    *,
    ledger: Path | None = None,
    task_id: str | None = None,
    author_id: int = DEFAULT_AUTHOR_ID,
    plan: ImplementationPlan | None = None,
    approval: ReviewAuthorization | None = None,
) -> dict:
    store = ReadOnlyStore(database)
    with store.snapshot():
        with store.connection() as conn:
            row = conn.execute(
                "SELECT * FROM github_intake WHERE issue_number=?", (issue,)
            ).fetchone()
            if row is None:
                return {
                    "status": "REJECTED",
                    "reason": "NO_CHECKPOINT",
                    "issue_number": issue,
                    "execution_enabled": False,
                }
            result = {
                key: row[key]
                for key in (
                    "issue_number",
                    "issue_id",
                    "issue_url",
                    "author_id",
                    "source_mode",
                    "research_date",
                    "body_sha256",
                    "proposal_sha256",
                    "task_id",
                )
            }
            result.update(
                admission=row["status"], admission_reason=row["reason"], execution_enabled=False
            )
            if row["status"] != "ACCEPTED":
                status = (
                    "INSUFFICIENT_INFORMATION"
                    if row["reason"] == "INVALID_PROPOSAL"
                    else "REJECTED"
                )
                return result | {"status": status, "reason": row["reason"] or row["status"]}
            try:
                proposal, task = _proposal(conn, row, task_id, author_id)
            except ValidationError:
                return result | {"status": "INSUFFICIENT_INFORMATION", "reason": "INVALID_PROPOSAL"}
            except ValueError as exc:
                return result | {"status": "REJECTED", "reason": str(exc)}
            blockers = _work_blockers(conn, task)
            if proposal.origin == TECHNICAL_PILOT_ORIGIN:
                blockers.append(PILOT_PREPARATION_BLOCKED)
    budget = {"monthly_cap_cents": MONTHLY_CAP_CENTS, "available_cents": None}
    if ledger is None or ledger.resolve() == store.path:
        budget["status"] = "CANONICAL_LEDGER_REQUIRED"
    else:
        try:
            available = Budget(ReadOnlyStore(ledger)).available()
            budget.update(
                available_cents=available, status="AVAILABLE" if available > 0 else "EXHAUSTED"
            )
        except (OSError, sqlite3.Error, ValueError) as exc:
            budget.update(status="BLOCKED", reason=str(exc))
    if budget["status"] != "AVAILABLE":
        blockers.append("BUDGET_REVIEW_REQUIRED")
    return result | {
        "hypothesis_id": proposal.manifest.hypothesis_id,
        "candidate_id": task["candidate_id"],
        "origin": proposal.origin,
        "source_url": proposal.source_url,
        "queue_state": [task["kind"], task["mode"], task["status"]],
        "authorization": _check_authorization(approval, plan, row, proposal.manifest),
        "local_plan": (
            {
                "sha256": digest(canonical(plan.model_dump(mode="json"))),
                **plan.model_dump(mode="json"),
                "expected_files": plan.paths(),
                "quick_checks": plan.checks(),
            }
            if plan is not None
            else None
        ),
        "budget": budget,
        "work_blockers": blockers,
        **_technical(proposal.manifest),
    }
