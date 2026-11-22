"""Bounded auditor-profile reads and primary-source/catalogue correspondence."""

from pathlib import Path

from trading_lab_catalog.read_api import CatalogReader
from trading_lab_catalog.read_models import public_data
from trading_lab_catalog.verification import parse
from trading_lab_orchestration.contracts import canonical

from .context import ContextLimits, ResearchError
from .models import identity
from .validator_evidence import AuditPinConflict, PreparedAudit, reconcile_scientific_histories
from .validator_models import ValidationRequest


class ValidatorContext:
    def __init__(self, path: Path, *, fixture_root: Path, limits: ContextLimits | None = None):
        path, root = Path(path).absolute(), Path(fixture_root).absolute()
        if (
            ".." in path.parts
            or ".." in root.parts
            or not path.is_relative_to(root)
            or path == root
        ):
            raise ValueError("Explicit disposable catalogue root required")
        self._profile = CatalogReader(path).for_profile("auditor")
        self.limits = ContextLimits.model_validate((limits or ContextLimits()).model_dump())

    def capture(self, request: ValidationRequest, sources: dict[str, PreparedAudit]) -> dict:
        metrics = {"queries": 0}
        for attempt in range(1, 4):
            try:
                payload = self._capture(request, sources, metrics)
                payload["metrics"] = {**metrics, "captures": attempt}
                return payload
            except ResearchError as exc:
                if exc.code != "CURSOR_INVALIDATED" or attempt == 3:
                    raise
        raise AssertionError("Unreachable")

    def _capture(self, request, sources, metrics):
        checkpoint = None
        references, graphs, audits, all_cases = {}, [], [], {}
        total_bytes = 0

        def query(operation, **args):
            nonlocal checkpoint, total_bytes
            if metrics["queries"] >= self.limits.max_queries:
                raise ResearchError("CONTEXT_QUERY_LIMIT")
            metrics["queries"] += 1
            response = self._profile.query(operation, **args)
            code = response.get("status")
            if code != "OK":
                raise ResearchError(
                    code
                    if code
                    in {
                        "CURSOR_INVALIDATED",
                        "NOT_FOUND",
                        "BLOCKED",
                        "INTEGRITY_ERROR",
                        "RESPONSE_LIMIT_EXCEEDED",
                        "QUERY_LIMIT_EXCEEDED",
                    }
                    else "CATALOGUE_INVALID"
                )
            current = response.get("checkpoint")
            if type(current) is not str or len(current) != 64:
                raise ResearchError("CATALOGUE_INVALID")
            if checkpoint is not None and current != checkpoint:
                raise ResearchError("CURSOR_INVALIDATED")
            if request.expected_checkpoint is not None and current != request.expected_checkpoint:
                raise ResearchError("CHECKPOINT_CHANGED")
            checkpoint = current
            total_bytes += len(canonical(response).encode())
            if total_bytes > self.limits.max_bytes:
                raise ResearchError("CONTEXT_LIMIT_EXCEEDED")
            return response["items"]

        def reference(kind, key, **data):
            ref = "catalog." + identity(kind, {"id": key})
            value = {"reference_id": ref, "kind": kind, "entity_id": key, **data}
            if ref in references and references[ref] != value:
                raise ResearchError("EVIDENCE_CONFLICT")
            references[ref] = value
            return ref

        for run_id in request.source_run_ids:
            rows = query("get_run_details", run_id=run_id)
            summaries = query("get_evidence_summary", run_id=run_id)
            if len(rows) != 1 or len(summaries) != 1:
                raise ResearchError("CATALOGUE_INVALID")
            graph, summary = rows[0], summaries[0]
            run, exp = graph["run"], graph["experiment"]
            if (
                run["id"] != run_id
                or summary["run_id"] != run_id
                or run["experiment_id"] != exp["id"]
            ):
                raise ResearchError("CATALOGUE_LINEAGE_MISMATCH")
            if (
                summary["audit_status"] != run["audit_status"]
                or summary["evidence_sha256"] != run["evidence_sha256"]
                or summary["artifacts"] != graph["artifacts"]
            ):
                raise ResearchError("EVIDENCE_CONFLICT")
            source = sources[run_id]
            try:
                primary = source.validate_for_graph(graph)
            except AuditPinConflict as exc:
                exc.evidence_diagnostic["checkpoint"] = checkpoint
                raise
            audits.append(primary)
            references[primary["reference_id"]] = {
                "reference_id": primary["reference_id"],
                "kind": "PRIMARY_AUDIT",
                "entity_id": primary["audit_id"],
                "sha256": primary["sha256"],
                "effective_status": "HASH_VERIFIED",
            }
            provenance = {r["entity_id"]: r for r in summary["provenance"]}
            if len(provenance) != len(summary["provenance"]):
                raise ResearchError("EVIDENCE_PROVENANCE_AMBIGUOUS")
            primary["identity_pins"]["run_record_fingerprint"] = {
                "domain": "CATALOGUE_RUN_RECORD_FINGERPRINT",
                "sha256": provenance.get(run_id, {}).get("record_fingerprint"),
            }
            run_ref = reference(
                "RUN",
                run_id,
                record_fingerprint=provenance.get(run_id, {}).get("record_fingerprint"),
                effective_status=run["audit_status"],
            )
            projected_cases = []
            for case in graph["case_results"]:
                if case["run_id"] != run_id or case["id"] in all_cases:
                    raise ResearchError("CATALOGUE_CASE_IDENTITY_MISMATCH")
                all_cases[case["id"]] = case
                ref = reference(
                    "CASE",
                    case["id"],
                    record_fingerprint=provenance.get(case["id"], {}).get("record_fingerprint"),
                    effective_status=case["audit_status"],
                )
                fields = {
                    "id",
                    "run_id",
                    "segment",
                    "scenario",
                    "period_start_utc",
                    "period_end_utc",
                    "warmup_bars",
                    "trades",
                    "net_return_pct",
                    "max_drawdown_pct",
                    "win_rate_pct",
                    "profit_factor",
                    "capital_initial",
                    "costs",
                    "metrics",
                    "audit_status",
                    "run_audit_status",
                    "case_audit_status",
                    "holdout",
                    "capital_policy",
                    "asset",
                    "timeframe",
                    "market_type",
                    "direction",
                    "dataset_sha256",
                    "engine",
                    "engine_version",
                    "kind",
                }
                row = parse(canonical({k: v for k, v in case.items() if k in fields}))
                row["reference_id"] = ref
                row["metric_availability"] = {
                    k: "SOURCE_NULL" if row["metrics"][k] is None else "SOURCE_VALUE"
                    for k in row["metrics"]
                }
                for k in ("sharpe", "p_value"):
                    if k not in row["metrics"]:
                        row["metrics"][k] = None
                        row["metric_availability"][k] = "ABSENT"
                row["statistical_significance"] = "UNKNOWN"
                projected_cases.append(row)
            artifacts = []
            for a in graph["artifacts"]:
                if a["run_id"] != run_id:
                    raise ResearchError("CATALOGUE_LINEAGE_MISMATCH")
                ref = reference(
                    "ARTIFACT",
                    a["id"],
                    sha256=a["sha256"],
                    effective_status=a["verification_status"],
                )
                artifacts.append(
                    {
                        "id": a["id"],
                        "artifact_type": a["artifact_type"],
                        "sha256": a["sha256"],
                        "verification_status": a["verification_status"],
                        "reference_id": ref,
                    }
                )
            decisions = [
                {k: d[k] for k in ("id", "category", "verdict", "limitations")}
                for d in graph["decisions"]
            ]
            graphs.append(
                {
                    "run_id": run_id,
                    "run_reference_id": run_ref,
                    "primary_reference_id": primary["reference_id"],
                    "experiment_id": exp["id"],
                    "engine": run["engine"],
                    "engine_version": run["engine_version"],
                    "status": run["status"],
                    "kind": run["kind"],
                    "audit_status": run["audit_status"],
                    "evidence_sha256": run["evidence_sha256"],
                    "holdout": exp["holdout"],
                    "capital_policy": exp["capital_policy"],
                    "cases": projected_cases,
                    "artifacts": artifacts,
                    "source_decisions": decisions,
                }
            )
        if len(all_cases) > 40 or len(references) > 50:
            raise ResearchError("CONTEXT_ENTITY_LIMIT")
        consistency = reconcile_scientific_histories(audits, checkpoint)
        comparisons = query("compare_results", case_ids=sorted(all_cases))
        if len(comparisons) != 1:
            raise ResearchError("COMPARISON_INVALID")
        comparison = comparisons[0]
        if (
            sorted(comparison["case_ids"]) != sorted(all_cases)
            or comparison["winner"] is not None
            or {r["id"]: r for r in comparison["cases"]} != all_cases
        ):
            raise ResearchError("COMPARISON_CONTRADICTION")
        comparison = {k: v for k, v in comparison.items() if k != "cases"}
        result = {
            "checkpoint": checkpoint,
            "runs": graphs,
            "primary_audits": audits,
            "history_consistency": consistency,
            "references": list(references.values()),
            "comparison": comparison,
            "scope": "SIMULATION_READ_ONLY_NO_NEW_AUDIT_OR_AUTHORIZATION",
        }
        if public_data(result) != result:
            raise ResearchError("PRIVATE_PROVIDER_CONTEXT")
        if len(canonical(result).encode()) > self.limits.max_bytes:
            raise ResearchError("CONTEXT_LIMIT_EXCEEDED")
        return result
