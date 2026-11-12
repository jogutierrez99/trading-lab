"""Manual intake, bounded implementation and deterministic isolated backtest execution."""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from pydantic import ValidationError

from .codex_adapter import CodexCLI
from .contracts import canonical, digest, load_manifest
from .implementation import Coordinator, load_plan
from .store import Store, database_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="SQLite path; overrides TRADING_LAB_ORCHESTRATOR_DB")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "register"):
        commands.add_parser(command).add_argument("manifest", type=Path)
    commands.add_parser("list")
    commands.add_parser("show").add_argument("identifier")
    transition = commands.add_parser("transition")
    transition.add_argument("candidate_id")
    transition.add_argument("--from", dest="expected", required=True)
    transition.add_argument("--to", dest="target", required=True)
    transition.add_argument("--reason", required=True)
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--codex-executable", default="codex")
    for name in ("prepare", "process"):
        prepare = commands.add_parser(name)
        prepare.add_argument("task_id")
        prepare.add_argument("--plan", type=Path, required=True)
        prepare.add_argument("--repo", type=Path, default=Path.cwd())
        prepare.add_argument("--artifacts", type=Path, required=True)
        prepare.add_argument("--repair", action="store_true")
        if name == "process":
            prepare.add_argument("--codex-executable", default="codex")
    run = commands.add_parser("run")
    run.add_argument("attempt_id")
    run.add_argument("--codex-executable", default="codex")
    run.add_argument("--windows-sandbox", choices=("elevated", "mxc"))
    commands.add_parser("attempt").add_argument("attempt_id")
    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("attempt_id")
    reconcile.add_argument("--outcome", choices=["verify", "failed", "cancel"], required=True)
    reconcile.add_argument("--confirm-stopped", action="store_true")
    reconcile.add_argument("--reason", required=True)
    format_repair = commands.add_parser("repair-format")
    format_repair.add_argument("attempt_id")
    format_repair.add_argument("--confirm-stopped", action="store_true")
    format_repair.add_argument("--reason", required=True)
    execution_prepare = commands.add_parser("prepare-execution")
    execution_prepare.add_argument("implementation_id")
    execution_prepare.add_argument("--plan", type=Path, required=True)
    execution_prepare.add_argument("--artifacts", type=Path, required=True)
    execution_prepare.add_argument("--retry-of")
    for name in ("validate-execution", "run-execution", "execution"):
        commands.add_parser(name).add_argument("execution_id")
    execution_reconcile = commands.add_parser("reconcile-execution")
    execution_reconcile.add_argument("execution_id")
    execution_reconcile.add_argument(
        "--outcome", choices=["verify", "failed", "cancel"], required=True
    )
    execution_reconcile.add_argument("--confirm-stopped", action="store_true")
    execution_reconcile.add_argument("--reason", required=True)
    technical = commands.add_parser("apply-technical-repair")
    technical.add_argument("source_attempt_id")
    technical.add_argument("--patch", type=Path, required=True)
    technical.add_argument("--artifacts", type=Path, required=True)
    technical.add_argument("--author", required=True)
    technical.add_argument("--authorization", required=True)
    commands.add_parser("technical-repair").add_argument("repair_id")
    repair_reconcile = commands.add_parser("reconcile-technical-repair")
    repair_reconcile.add_argument("repair_id")
    repair_reconcile.add_argument("--confirm-stopped", action="store_true")
    repair_reconcile.add_argument("--reason", required=True)
    audit = commands.add_parser("audit", help="Read-only audit of an exact existing execution")
    audit.add_argument("request", type=Path)
    audit.add_argument("--artifacts", type=Path, required=True)
    for name in ("audit-openai-doctor", "audit-openai"):
        command = commands.add_parser(name)
        command.add_argument("audit_id")
        command.add_argument("--source-db", type=Path, required=True)
        command.add_argument("--model", default="gpt-6.1-sol")
        if name == "audit-openai":
            command.add_argument("--billing-scope", nargs=2, metavar=("ORG_ID", "PROJECT_ID"))
            command.add_argument("--artifacts", type=Path, required=True)
            command.add_argument("--confirm-maximum-cents", type=int, required=True)
    for name in ("audit-show", "audit-reconcile", "notify-preview"):
        commands.add_parser(name).add_argument("audit_id")
    for name in ("notify-show", "notify-send"):
        command = commands.add_parser(name)
        command.add_argument("notification_id")
        if name == "notify-send":
            command.add_argument("--retry", action="store_true")
    notice = commands.add_parser("notify-reconcile")
    notice.add_argument("notification_id")
    notice.add_argument("--outcome", required=True, choices=["accepted", "not-sent", "uncertain"])
    notice.add_argument("--reason", required=True)
    notice.add_argument("--message-id", type=int)
    notice.add_argument("--confirm-stopped", action="store_true")
    commands.add_parser("api-budget")
    opening = commands.add_parser("api-budget-open")
    opening.add_argument("--opening-spend-cents", type=int, required=True)
    opening.add_argument("--provenance", required=True)
    billing = commands.add_parser("api-budget-reconcile")
    billing.add_argument("call_id")
    billing.add_argument("--actual-cents", type=int, required=True)
    billing.add_argument("--provenance", required=True)
    for name in ("api-budget-billing-doctor", "api-budget-billing-reconcile"):
        evidence = commands.add_parser(name, help="Attribute OpenAI costs without invoking models")
        evidence.add_argument("call_id")
        evidence.add_argument("--usage-csv", type=Path)
        evidence.add_argument("--costs-csv", type=Path)
        evidence.add_argument("--prior-usage-csv", type=Path)
        evidence.add_argument("--prior-costs-csv", type=Path)
        evidence.add_argument("--project-id")
        evidence.add_argument("--admin", action="store_true")
        evidence.add_argument("--exclusive-billing-scope", action="store_true")
    for name in ("research-doctor", "research-intake"):
        research = commands.add_parser(
            name, help="Under-demand research intake; stops at the queue"
        )
        research.add_argument("batch", type=Path)
        research.add_argument("--budget-db", type=Path, required=True)
        research.add_argument("--profile", choices=("standard", "reduced"), default="standard")
        if name == "research-intake":
            research.add_argument("--billing-scope", nargs=2, metavar=("ORG_ID", "PROJECT_ID"))
            research.add_argument("--artifacts", type=Path, required=True)
            research.add_argument("--confirm-maximum-cents", type=int, required=True)
    pilot = commands.add_parser(
        "verify-pilot", help="Read-only historical verification; no run or send"
    )
    pilot.add_argument("request", type=Path)
    pilot.add_argument("--format", choices=["json", "text"], default="json")
    pilot.add_argument(
        "--output", type=Path, help="Export new JSON/Markdown outside inspected sources"
    )
    for name in ("circuit-doctor", "circuit-run"):
        circuit = commands.add_parser(name)
        circuit.add_argument("request", type=Path)
        circuit.add_argument("--repo", type=Path, default=Path.cwd())
        circuit.add_argument("--artifacts", type=Path, required=True)
        circuit.add_argument("--codex-executable", default="codex")
        if name == "circuit-run":
            circuit.add_argument("--resume", action="store_true")
    commands.add_parser("circuit-show").add_argument("circuit_id")
    for name in ("flow1-bind", "flow1-draft", "flow1-billing-cycle"):
        flow = commands.add_parser(name)
        flow.add_argument("--budget-db", type=Path, required=True)
        flow.add_argument("--research-dossier", type=Path, required=True)
        if name in {"flow1-draft", "flow1-billing-cycle"}:
            flow.add_argument("--model-dossier", type=Path, required=True)
        if name == "flow1-billing-cycle":
            flow.add_argument("call_id")
            flow.add_argument("--project-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in {"research-doctor", "research-intake"}:
            from .audit_model import Budget, ExistingBudgetStore
            from .audit_openai import OpenAIResponses, load_openai_key
            from .research_intake import (
                RESEARCH_MODELS,
                ingest,
                load_batch,
                pricing_profile,
                request_body,
            )

            batch = load_batch(args.batch)
            canonical_db = os.environ.get("TRADING_LAB_GLOBAL_API_DB")
            ledger = database_path(str(args.budget_db))
            if not canonical_db or ledger != database_path(canonical_db):
                raise ValueError("Use the canonical ledger in TRADING_LAB_GLOBAL_API_DB")
            key = load_openai_key(Path(__file__).resolve().parents[2] / ".env")
            if args.command == "research-doctor":
                pricing = pricing_profile(args.profile)
                blockers = [] if key else ["OPENAI_API_KEY_ABSENT"]
                available = None
                try:
                    available = Budget(ExistingBudgetStore(ledger)).available()
                    if available < pricing["maximum_cents"]:
                        blockers.append("GLOBAL_API_BUDGET_EXHAUSTED")
                except (OSError, ValueError, sqlite3.Error) as exc:
                    blockers.append(str(exc))
                result = {
                    "status": "BLOCKED" if blockers else "READY",
                    "batch_sha256": digest(canonical(batch.model_dump(mode="json"))),
                    "ideas": len(batch.ideas),
                    "request_bytes": len(request_body(batch, args.profile)),
                    "openai_api_key_present": bool(key),
                    "monthly_cap_eur": 20,
                    "available_cents": available,
                    "pricing": pricing,
                    "blockers": blockers,
                }
            else:
                if not args.db:
                    raise ValueError("Explicit destination queue --db required")
                scope = {"billing_scope": args.billing_scope} if args.billing_scope else {}
                result = ingest(
                    batch,
                    Budget(ExistingBudgetStore(ledger)),
                    database_path(args.db),
                    args.artifacts,
                    (
                        OpenAIResponses(key, **scope)
                        if key and args.profile == "standard"
                        else OpenAIResponses(key, RESEARCH_MODELS[args.profile], **scope)
                        if key
                        else None
                    ),
                    args.confirm_maximum_cents,
                    profile=args.profile,
                )
            print(json.dumps(result, indent=2, ensure_ascii=True))
            return 0 if result["status"] in {"READY", "REGISTERED", "NEEDS_REVIEW"} else 2
        if args.command in {"audit-openai-doctor", "audit-openai"}:
            from .audit_model import Budget, ExistingBudgetStore
            from .audit_openai import (
                OpenAIResponses,
                load_openai_key,
                quote,
                responses_body,
                supplement,
                verified_source,
            )
            from .readonly import ReadOnlyStore

            canonical_db = os.environ.get("TRADING_LAB_GLOBAL_API_DB")
            if (
                not canonical_db
                or not args.db
                or database_path(args.db) != database_path(canonical_db)
            ):
                raise ValueError(
                    "Use the existing canonical global ledger in TRADING_LAB_GLOBAL_API_DB and --db"
                )
            ledger = ReadOnlyStore(database_path(args.db))
            source = ReadOnlyStore(args.source_db)
            key = load_openai_key(Path(__file__).resolve().parents[2] / ".env")
            pricing = quote(args.model)
            if args.command == "audit-openai-doctor":
                _, request, _, packet = verified_source(source, args.audit_id)
                blockers = [] if key else ["OPENAI_API_KEY_ABSENT"]
                try:
                    available = Budget(ledger).available()
                    if available < pricing["maximum_cents"]:
                        blockers.append("GLOBAL_API_BUDGET_EXHAUSTED")
                except ValueError as exc:
                    available = None
                    blockers.append(str(exc))
                with ledger.connection() as conn:
                    if conn.execute(
                        "SELECT 1 FROM api_calls WHERE purpose=?",
                        ("openai-audit-v1:" + request.execution_id,),
                    ).fetchone():
                        blockers.append("MODEL_REVIEW_ALREADY_RESERVED")
                result = {
                    "status": "BLOCKED" if blockers else "READY",
                    "blockers": blockers,
                    "openai_api_key_present": bool(key),
                    "pricing": pricing,
                    "available_cents": available,
                    "run_id": request.run_id,
                    "verified_cases": len(packet["cases"]),
                    "packet_utf8_bytes": len(canonical(packet).encode("utf-8")),
                    "responses_body_utf8_bytes": len(responses_body(args.model, packet)),
                    "network_calls": 0,
                }
            else:
                if not key:
                    raise ValueError("OPENAI_API_KEY_ABSENT")
                if args.confirm_maximum_cents != pricing["maximum_cents"]:
                    raise ValueError(
                        "Confirm the exact reservation shown by the offline diagnostic"
                    )
                # Early read-only balance guard. The write transaction checks again before sending.
                if Budget(ledger).available() < pricing["maximum_cents"]:
                    raise ValueError("GLOBAL_API_BUDGET_EXHAUSTED")
                result = supplement(
                    source,
                    Budget(ExistingBudgetStore(ledger.path)),
                    args.audit_id,
                    args.artifacts,
                    OpenAIResponses(key, args.model, billing_scope=args.billing_scope),
                    args.confirm_maximum_cents,
                )
            print(json.dumps(result, indent=2, ensure_ascii=True))
            return 0 if result["status"] in {"READY", "COMPLETED"} else 2
        elif args.command in {"flow1-bind", "flow1-draft", "flow1-billing-cycle"}:
            from .audit_model import Budget, ExistingBudgetStore
            from .flow1 import billing_cycle, draft, research_request
            from .readonly import ReadOnlyStore

            canonical_db = os.environ.get("TRADING_LAB_GLOBAL_API_DB")
            if (
                not args.db
                or not canonical_db
                or database_path(str(args.budget_db)) != database_path(canonical_db)
            ):
                raise ValueError(
                    "Flow 1 requires the explicit trial DB and canonical global ledger"
                )
            trial = ReadOnlyStore(database_path(args.db))
            budget = Budget(ReadOnlyStore(args.budget_db))
            if args.command == "flow1-billing-cycle":
                result = billing_cycle(
                    trial,
                    Budget(ExistingBudgetStore(args.budget_db)),
                    args.research_dossier,
                    args.model_dossier,
                    args.call_id,
                    args.project_id,
                )
            elif args.command == "flow1-bind":
                request, _ = research_request(trial, budget, args.research_dossier)
                result = request.model_dump(mode="json")
            else:
                result = draft(Store(trial.path), budget, args.research_dossier, args.model_dossier)
            print(json.dumps(result, indent=2, ensure_ascii=True))
            return 0
        elif args.command in {"circuit-doctor", "circuit-run", "circuit-show"}:
            from .circuit import CircuitRunner, check_acceptance_database, circuit_doctor
            from .circuit_contracts import ACCEPTANCE_RESEARCHER, CircuitRequest
            from .readonly import ReadOnlyStore

            if args.command == "circuit-show":
                result = CircuitRunner(ReadOnlyStore(database_path(args.db))).inspect(
                    args.circuit_id
                )
            else:
                request = CircuitRequest.model_validate_json(
                    args.request.read_text(encoding="utf-8-sig")
                )
                if request.manifest.researcher_version == ACCEPTANCE_RESEARCHER:
                    if not args.db:
                        raise ValueError("Acceptance requires an explicit isolated --db path")
                    check_acceptance_database(database_path(args.db), request)
                if args.command == "circuit-doctor":
                    result = circuit_doctor(
                        database_path(args.db),
                        request,
                        args.repo,
                        args.artifacts,
                        args.codex_executable,
                    )
                else:
                    runner = CircuitRunner(Store(database_path(args.db)))
                    runner.on_progress = lambda event: print(
                        json.dumps(event), file=sys.stderr, flush=True
                    )
                    result = runner.start(
                        request,
                        args.repo,
                        args.artifacts,
                        args.codex_executable,
                        resume=args.resume,
                    )
            print(json.dumps(result, indent=2, ensure_ascii=True))
            if args.command == "circuit-show":
                return 0
            return (
                0
                if result["status"]
                in {
                    "LOCAL_PREFLIGHT_OK",
                    "NOTICE_PREPARED",
                    "AWAITING_MODEL_AUDIT",
                }
                else 2
            )
        elif args.command == "verify-pilot":
            from .pilot import PilotVerifier, export_pilot, render_pilot
            from .pilot_contracts import PilotVerificationRequest

            request = PilotVerificationRequest.model_validate_json(
                args.request.read_text(encoding="utf-8-sig")
            )
            verification = PilotVerifier(database_path(args.db)).verify(request)
            result = verification.model_dump(mode="json")
            export_failed = False
            if args.output:
                try:
                    result["export"] = export_pilot(verification, args.output)
                except (OSError, ValueError) as exc:
                    export_failed = True
                    result["export_error"] = {"kind": type(exc).__name__, "message": str(exc)[:600]}
            if args.format == "text":
                print(render_pilot(verification))
                if "export" in result:
                    print(json.dumps(result["export"], indent=2))
                if export_failed:
                    print(json.dumps(result["export_error"], indent=2))
            else:
                print(json.dumps(result, indent=2, ensure_ascii=True))
            return (
                0
                if (
                    verification.status == "VERIFIED_HISTORICAL_TECHNICAL_PILOT"
                    and not export_failed
                )
                else 2
            )
        elif args.command in {"audit", "audit-show", "audit-reconcile"}:
            from .audit import Auditor
            from .audit_contracts import AuditRequest

            if args.command == "audit":
                request = AuditRequest.model_validate_json(
                    args.request.read_text(encoding="utf-8-sig")
                )
                auditor = Auditor(Store(database_path(args.db)))
                result = auditor.run(request, args.artifacts)
            else:
                auditor = Auditor(Store(database_path(args.db)))
                result = (
                    auditor.inspect(args.audit_id)
                    if args.command == "audit-show"
                    else auditor.reconcile(args.audit_id)
                )
        elif args.command.startswith("notify-"):
            from .audit_notifications import Outbox

            outbox = Outbox(Store(database_path(args.db)))
            if args.command == "notify-preview":
                result = outbox.preview(args.audit_id)
            elif args.command == "notify-send":
                result = outbox.send(args.notification_id, retry=args.retry)
            elif args.command == "notify-reconcile":
                result = outbox.reconcile(
                    args.notification_id,
                    outcome=args.outcome,
                    reason=args.reason,
                    message_id=args.message_id,
                    confirm_stopped=args.confirm_stopped,
                )
            else:
                result = outbox.get(args.notification_id)
        elif args.command.startswith("api-budget"):
            from .audit_model import Budget, ExistingBudgetStore

            ledger = database_path(args.db)
            if args.command.startswith("api-budget-billing-"):
                from .billing import reconcile as reconcile_billing

                canonical_db = os.environ.get("TRADING_LAB_GLOBAL_API_DB")
                if not canonical_db or ledger != database_path(canonical_db):
                    raise ValueError("Use the canonical ledger in TRADING_LAB_GLOBAL_API_DB")
                result = reconcile_billing(
                    Budget(ExistingBudgetStore(ledger)),
                    args.call_id,
                    usage_csv=args.usage_csv,
                    costs_csv=args.costs_csv,
                    prior_usage_csv=args.prior_usage_csv,
                    prior_costs_csv=args.prior_costs_csv,
                    project=args.project_id,
                    admin=args.admin,
                    exclusive=args.exclusive_billing_scope,
                    apply=args.command == "api-budget-billing-reconcile",
                )
                print(json.dumps(result, indent=2, ensure_ascii=True))
                return 2 if result["status"] == "BLOCKED" else 0
            budget = Budget(ExistingBudgetStore(ledger))
            if args.command == "api-budget-open":
                budget.open_month(args.opening_spend_cents, args.provenance)
            elif args.command == "api-budget-reconcile":
                from .processes import coordinator_lock

                with coordinator_lock(budget.store.path.with_suffix(".openai-audit.lock")):
                    budget.settle(args.call_id, args.actual_cents, args.provenance)
            result = budget.inspect()
        elif args.command in {
            "apply-technical-repair",
            "technical-repair",
            "reconcile-technical-repair",
        }:
            from .manual_repair import ManualRepair

            repair = ManualRepair(Store(database_path(args.db)))
            if args.command == "apply-technical-repair":
                result = repair.apply(
                    args.source_attempt_id,
                    args.patch,
                    args.artifacts,
                    args.author,
                    args.authorization,
                )
            elif args.command == "technical-repair":
                result = repair.inspect(args.repair_id)
            else:
                result = repair.reconcile(args.repair_id, args.confirm_stopped, args.reason)
        elif args.command in {
            "prepare-execution",
            "validate-execution",
            "run-execution",
            "execution",
            "reconcile-execution",
        }:
            from .execution import Executor
            from .execution_contracts import ExecutionPlan

            executor = Executor(Store(database_path(args.db)))
            if args.command == "prepare-execution":
                plan = ExecutionPlan.model_validate_json(args.plan.read_text(encoding="utf-8-sig"))
                result = executor.prepare(
                    args.implementation_id, plan, args.artifacts, args.retry_of
                )
            elif args.command == "validate-execution":
                result = executor.validate(args.execution_id)
            elif args.command == "run-execution":
                result = executor.run(args.execution_id)
            elif args.command == "execution":
                result = executor.inspect(args.execution_id)
            else:
                result = executor.reconcile(
                    args.execution_id, args.outcome, args.confirm_stopped, args.reason
                )
        elif args.command == "doctor":
            result = CodexCLI(args.codex_executable).probe(Path.cwd())
            result.pop("exec_help", None)
        elif args.command in {"prepare", "process", "run", "attempt", "reconcile", "repair-format"}:
            coordinator = Coordinator(Store(database_path(args.db)))
            if args.command in {"prepare", "process"}:
                result = coordinator.prepare(
                    args.task_id, args.repo, args.artifacts, load_plan(args.plan), args.repair
                )
                if args.command == "process" and result["status"] == "PREPARED":
                    result = coordinator.run(result["attempt_id"], args.codex_executable)
            elif args.command == "run":
                result = coordinator.run(
                    args.attempt_id, args.codex_executable, windows_sandbox=args.windows_sandbox
                )
            elif args.command == "attempt":
                result = coordinator.inspect(args.attempt_id)
            elif args.command == "repair-format":
                result = coordinator.repair_format(
                    args.attempt_id, args.confirm_stopped, args.reason
                )
            else:
                result = coordinator.reconcile(
                    args.attempt_id, args.outcome, args.confirm_stopped, args.reason
                )
        elif args.command in {"validate", "register"}:
            manifest = load_manifest(args.manifest)
            if args.command == "validate":
                result = {
                    "valid": True,
                    "hypothesis_id": manifest.hypothesis_id,
                    "manifest_sha256": digest(manifest.snapshot()),
                    "fingerprint": manifest.fingerprint(),
                }
            else:
                result = Store(database_path(args.db)).register(manifest)
        else:
            store = Store(database_path(args.db))
            if args.command == "list":
                result = {"database": str(store.path), "candidates": store.list_candidates()}
            elif args.command == "show":
                result = store.show(args.identifier)
            else:
                result = store.transition(
                    args.candidate_id, args.expected, args.target, args.reason
                )
        print(json.dumps(result, indent=2, ensure_ascii=True))
        if args.command in {"audit", "audit-reconcile"}:
            return 0 if result["status"] == "COMPLETED_WITH_LIMITATIONS" else 2
        if args.command == "notify-send":
            return 0 if result["status"] == "ACCEPTED" else 2
        if args.command in {
            "prepare",
            "process",
            "run",
            "reconcile",
            "repair-format",
            "apply-technical-repair",
            "reconcile-technical-repair",
            "prepare-execution",
            "validate-execution",
            "run-execution",
            "reconcile-execution",
        }:
            return 0 if result["status"] in {"PREPARED", "SUCCEEDED", "CANCELLED"} else 2
        return 0
    except ValidationError as exc:
        error = {
            "error": (
                {"audit": "INVALID_AUDIT_REQUEST", "verify-pilot": "INVALID_PILOT_REQUEST"}.get(
                    args.command, "INVALID_MANIFEST"
                )
            ),
            "details": exc.errors(include_input=False, include_context=False),
        }
    except (OSError, ValueError, sqlite3.Error) as exc:
        error = {"error": type(exc).__name__, "message": str(exc)}
    print(json.dumps(error, indent=2, ensure_ascii=True))
    return 2
