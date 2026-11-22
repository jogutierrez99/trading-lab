"""Captured host evidence, never a filesystem resolver or an audit execution tool."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import Field, TypeAdapter

from trading_lab_catalog.verification import parse, sha
from trading_lab_orchestration.audit_contracts import AuditRequest, AuditVerdict
from trading_lab_orchestration.contracts import Period, canonical

from .context import ResearchError
from .designer_models import strict_json
from .models import SHA, CatalogID, Contract, Text, identity

MANIFEST_DOMAIN = "HYPOTHESIS_MANIFEST_JSON_SHA256"
HISTORY_SCOPE = "HypothesisManifest.novelty/1.0"
HISTORY_COUNTERS = ("known_searches", "known_variants")


class ScientificHistoryConflict(ResearchError):
    """Comparable frozen-manifest declarations disagree; no model may reconcile."""

    def __init__(self, conflicts, checkpoint):
        super().__init__("SCIENTIFIC_HISTORY_CONFLICT")
        self.evidence_diagnostic = {
            "kind": "SCIENTIFIC_HISTORY_CONFLICT",
            "checkpoint": checkpoint,
            "conflicts": conflicts,
        }


def _manifest_identity(verdict, saved, reference_id):
    raw = verdict.observations.get("hypothesis_manifest_sha256")
    if raw is not None:
        try:
            raw = TypeAdapter(SHA).validate_python(raw, strict=True)
        except ValueError:
            raise ResearchError("AUDIT_MANIFEST_IDENTITY_INVALID") from None
    declared_scope = verdict.observations.get("search_history_scope", HISTORY_SCOPE)
    if declared_scope is not None and (
        type(declared_scope) is not str or not 1 <= len(declared_scope) <= 160
    ):
        raise ResearchError("AUDIT_HISTORY_SCOPE_INVALID")
    host_scope = saved["history_scope"]
    bound = raw is not None and saved["manifest_identity_verified"]
    return {
        "domain": MANIFEST_DOMAIN,
        "candidate_id": verdict.candidate_id,
        "hypothesis_manifest_sha256": raw,
        "availability": "ABSENT"
        if "hypothesis_manifest_sha256" not in verdict.observations
        else "NULL"
        if raw is None
        else "PRESENT",
        "binding_status": "HOST_AUDIT_DECLARATION_BOUND" if bound else "UNVERIFIED",
        "history_scope": {
            "host": host_scope,
            "declared": declared_scope,
            "status": "VERIFIED_NOVELTY_V1"
            if host_scope == declared_scope == HISTORY_SCOPE
            else "UNVERIFIED_SCOPE",
        },
        "provenance": {
            "audit_reference_id": reference_id,
            "audit_id": verdict.audit_id,
            "audit_sha256": saved["expected_sha256"],
            "origin_field": "observations.hypothesis_manifest_sha256",
            "producer": verdict.auditor_profile,
            "producer_version": verdict.auditor_version,
        },
    }


def reconcile_scientific_histories(audits: list[dict], checkpoint: str) -> dict:
    """Only explicit integers in the same accredited frozen scope can conflict.

    Candidate IDs, names, parameter fingerprints or equal assets alone establish
    no scientific equivalence. No counter is filled, summed or selected here.
    """
    groups, issues, bindings = {}, [], []
    by_candidate, by_manifest = {}, {}
    for audit in sorted(audits, key=lambda a: a["reference_id"]):
        binding = audit["manifest_identity"]
        ref = audit["reference_id"]
        bindings.append(
            {
                "reference_id": ref,
                "candidate_id": binding["candidate_id"],
                "hypothesis_manifest_sha256": binding["hypothesis_manifest_sha256"],
                "binding_status": binding["binding_status"],
                "history_scope": binding["history_scope"],
            }
        )
        candidate, manifest = binding["candidate_id"], binding["hypothesis_manifest_sha256"]
        history = audit["scientific_history"]["search_history"]
        known = any(
            k in history["fields_present"] and history[k] is not None for k in HISTORY_COUNTERS
        )
        by_candidate.setdefault(candidate, []).append(audit)
        if binding["binding_status"] != "HOST_AUDIT_DECLARATION_BOUND":
            if manifest is not None:
                issues.append({"code": "UNVERIFIED_HOST_IDENTITY_BINDING", "references": [ref]})
            continue
        by_manifest.setdefault(manifest, []).append(audit)
        if binding["history_scope"]["status"] != "VERIFIED_NOVELTY_V1":
            if known:
                issues.append({"code": "UNVERIFIED_COUNTER_SCOPE", "references": [ref]})
            continue
        groups.setdefault((candidate, manifest), []).append(audit)
    conflicts, summaries = [], []
    for (candidate, manifest), members in sorted(groups.items()):
        fields, checks = [], {}
        for field in HISTORY_COUNTERS:
            explicit, null, absent = [], [], []
            values = set()
            for member in members:
                history = member["scientific_history"]["search_history"]
                if field not in history["fields_present"]:
                    absent.append(member["reference_id"])
                elif history[field] is None:
                    null.append(member["reference_id"])
                else:
                    explicit.append(member["reference_id"])
                    values.add(history[field])
            if len(values) > 1:
                fields.append(field)
            checks[field] = {
                "status": "CONTRADICTION"
                if len(values) > 1
                else "UNKNOWN"
                if not values
                else "PARTIAL_KNOWLEDGE"
                if null or absent
                else "AGREEMENT"
                if len(members) > 1
                else "SINGLE_SOURCE",
                "explicit_references": sorted(explicit),
                "null_references": sorted(null),
                "absent_references": sorted(absent),
            }
        group = {
            "candidate_id": candidate,
            "hypothesis_manifest_sha256": manifest,
            "domain": MANIFEST_DOMAIN,
            "scope": HISTORY_SCOPE,
            "references": sorted(m["reference_id"] for m in members),
            "field_checks": checks,
        }
        summaries.append(group)
        if fields:
            # Keep the actionable source references without exposing raw
            # coordinator identifiers in a public diagnostic.
            public_group = {k: v for k, v in group.items() if k != "candidate_id"}
            conflicts.append(
                {
                    **public_group,
                    "candidate_reference_id": "candidate."
                    + identity("CandidateReference", {"id": candidate}),
                    "fields": sorted(fields),
                }
            )
        elif any(check["status"] == "PARTIAL_KNOWLEDGE" for check in checks.values()):
            issues.append({"code": "PARTIAL_COUNTER_KNOWLEDGE", "references": group["references"]})
    if conflicts:
        raise ScientificHistoryConflict(conflicts, checkpoint)
    for members in by_candidate.values():
        accredited = {
            a["manifest_identity"]["hypothesis_manifest_sha256"]
            for a in members
            if a["manifest_identity"]["binding_status"] == "HOST_AUDIT_DECLARATION_BOUND"
        }
        if len(accredited) > 1:
            issues.append(
                {
                    "code": "CANDIDATE_HAS_DISTINCT_MANIFESTS",
                    "references": sorted(a["reference_id"] for a in members),
                }
            )
        elif len(members) > 1 and any(
            a["manifest_identity"]["binding_status"] != "HOST_AUDIT_DECLARATION_BOUND"
            and any(
                a["scientific_history"]["search_history"][k] is not None for k in HISTORY_COUNTERS
            )
            for a in members
        ):
            issues.append(
                {
                    "code": "INCOMPLETE_COMMON_IDENTITY",
                    "references": sorted(a["reference_id"] for a in members),
                }
            )
    for members in by_manifest.values():
        if len({a["manifest_identity"]["candidate_id"] for a in members}) > 1:
            issues.append(
                {
                    "code": "MANIFEST_HAS_DISTINCT_CANDIDATES",
                    "references": sorted(a["reference_id"] for a in members),
                }
            )
    issues.sort(key=canonical)
    return {
        "domain": MANIFEST_DOMAIN,
        "bindings": bindings,
        "groups": summaries,
        "issues": issues,
        "needs_review": bool(issues),
    }


class _SearchHistory(Contract):
    prior_work: Text | None = None
    known_searches: int | None = Field(default=None, ge=0)
    known_variants: int | None = Field(default=None, ge=0)


class _SelectionHistory(Contract):
    holdout_status: Literal["UNOBSERVED_DECLARED", "CONSUMED", "UNKNOWN"] | None = None
    holdout_risk: Text | None = None
    train: Period | None = None
    validation: Period | None = None
    test: Period | None = None
    walk_forward: Text | None = None
    primary_metric: Text | None = None
    falsification: Text | None = None
    robustness_plan: Text | None = None


class _DatasetIdentity(Contract):
    dataset_id: CatalogID
    kind: Text
    manifest_sha256: SHA
    parquet_sha256: SHA | None = None


class AuditPinConflict(ResearchError):
    """Safe, hash-bound contradiction details; never raw source paths or text."""

    def __init__(self, catalogue_sha256, source_sha256, verdict):
        super().__init__("AUDIT_CONFIGURATION_PIN_MISMATCH")
        self.evidence_diagnostic = {
            "domain": "RESOLVED_CONFIGURATION_BYTES_SHA256",
            "catalogue_sha256": catalogue_sha256,
            "source_sha256": source_sha256,
            "run_id": verdict.run_id,
            "experiment_id": verdict.experiment_id,
        }


def _scientific_history(verdict, reference_id, digest):
    result = {"reference_id": reference_id, "verdict_sha256": digest, "period_conflicts": []}
    for key, model in (
        ("search_history", _SearchHistory),
        ("selection_history", _SelectionHistory),
    ):
        value = verdict.observations.get(key)
        if value is not None and type(value) is not dict:
            raise ResearchError("AUDIT_HISTORY_INVALID")
        try:
            parsed = model.model_validate_json(canonical(value or {}))
        except ValueError:
            raise ResearchError("AUDIT_HISTORY_INVALID") from None
        result[key] = {
            **parsed.model_dump(mode="json"),
            "availability": "ABSENT"
            if key not in verdict.observations
            else "NULL"
            if value is None
            else "PRESENT",
            "fields_present": sorted(value or {}),
        }
    if len(canonical(result).encode()) > 16 * 1024:
        raise ResearchError("AUDIT_HISTORY_LIMIT")
    selection = _SelectionHistory.model_validate_json(
        canonical(verdict.observations.get("selection_history") or {})
    )
    periods = [getattr(selection, k) for k in ("train", "validation", "test")]
    known = [p for p in periods if p is not None]
    if any(a.end > b.start for a, b in zip(known, known[1:], strict=False)):
        raise ResearchError("AUDIT_SELECTION_PERIOD_CONFLICT")
    return result


def _identity_pins(verdict, docs, graph):
    experiment = graph["experiment"]
    key = "native:resolved.json"
    source_sha = verdict.references[key].sha256 if key in docs else None
    # This adapter's tested mapping is the existing native AuditRequest protocol:
    # configuration_sha256 denotes the captured resolved.json bytes. Other
    # protocols need an explicit reviewed mapping, never equality by digest alone.
    comparable = verdict.observations["protocol"] == AuditRequest.model_fields["protocol"].default
    if comparable and source_sha is not None and source_sha != experiment["configuration_sha256"]:
        raise AuditPinConflict(experiment["configuration_sha256"], source_sha, verdict)
    if key in docs and "resolved_configuration" in verdict.observations:
        if canonical(parse(docs[key])) != canonical(verdict.observations["resolved_configuration"]):
            raise ResearchError("AUDIT_RESOLVED_CONTENT_MISMATCH")
    identities = verdict.observations.get("dataset_identity")
    if identities is not None and (type(identities) is not list or len(identities) > 20):
        raise ResearchError("AUDIT_DATASET_IDENTITY_INVALID")
    datasets = []
    for item in identities or []:
        if type(item) is not dict:
            raise ResearchError("AUDIT_DATASET_IDENTITY_INVALID")
        if set(item) - (
            set(_DatasetIdentity.model_fields) | {"path", "provenance_files", "provenance_note"}
        ):
            raise ResearchError("AUDIT_DATASET_IDENTITY_INVALID")
        try:
            pin = _DatasetIdentity.model_validate_json(
                canonical({k: v for k, v in item.items() if k in _DatasetIdentity.model_fields})
            )
        except ValueError:
            raise ResearchError("AUDIT_DATASET_IDENTITY_INVALID") from None
        datasets.append(pin.model_dump(mode="json"))
    if len({p["dataset_id"] for p in datasets}) != len(datasets):
        raise ResearchError("AUDIT_DATASET_IDENTITY_CONFLICT")
    return {
        "configuration": {
            "catalogue_domain": "RESOLVED_CONFIGURATION_BYTES_SHA256"
            if comparable
            else "UNKNOWN_CONFIGURATION_IDENTITY",
            "source_domain": "RESOLVED_CONFIGURATION_BYTES_SHA256",
            "catalogue_sha256": experiment["configuration_sha256"],
            "source_sha256": source_sha,
            "status": "MATCHED_CAPTURED_BYTES"
            if source_sha is not None and comparable
            else "UNVERIFIED_MISSING_SOURCE_PIN"
            if source_sha is None
            else "UNVERIFIED_DOMAIN_BINDING",
        },
        "datasets": {
            "catalogue": {
                "domain": "CATALOGUE_DATASET_IDENTITY",
                "sha256": experiment["dataset_sha256"],
            },
            "source_pins": datasets,
            "manifest_domain": "DATASET_MANIFEST_BYTES_SHA256",
            "data_file_domain": "PARQUET_BYTES_SHA256",
            "mapping_status": "UNVERIFIED_NO_DOMAIN_BINDING",
            "availability": "ABSENT"
            if "dataset_identity" not in verdict.observations
            else "NULL"
            if identities is None
            else "PRESENT",
        },
        "experiment_parameter_fingerprint": {
            "domain": "PARAMETER_FINGERPRINT",
            "sha256": experiment["parameter_fingerprint"],
        },
        "experiment_record_fingerprint": None,
    }


@dataclass(frozen=True)
class AuditDocument:
    """Host-captured bytes. Keys/paths remain private and are not provider tools."""

    key: str
    content: bytes


class PreparedAudit:
    """A trusted host captures the already-produced verdict and its original bytes.

    Hashes check integrity, not authorship or a new economic audit. This class
    cannot mint SOURCE_AUDITED: that state is read from catalogue accreditations.
    The embedding Python host and supplied expected hashes are trusted inputs.
    """

    def __init__(
        self,
        verdict_bytes: bytes,
        *,
        expected_sha256: str,
        documents: tuple[AuditDocument, ...],
        case_bindings: dict[str, str],
        run_evidence_key: str = "execution_receipt",
        manifest_identity_verified: bool = True,
        history_scope: str | None = HISTORY_SCOPE,
    ):
        if type(verdict_bytes) is not bytes or len(verdict_bytes) > 64 * 1024:
            raise ResearchError("AUDIT_INPUT_LIMIT")
        if type(manifest_identity_verified) is not bool:
            raise ResearchError("AUDIT_HOST_MANIFEST_BINDING_INVALID")
        if history_scope is not None and (
            type(history_scope) is not str or not 1 <= len(history_scope) <= 160
        ):
            raise ResearchError("AUDIT_HISTORY_SCOPE_INVALID")
        if sha(verdict_bytes) != expected_sha256:
            raise ResearchError("AUDIT_HASH_MISMATCH")
        verdict = strict_json(verdict_bytes, AuditVerdict)
        if type(documents) is not tuple or any(type(d) is not AuditDocument for d in documents):
            raise ResearchError("AUDIT_DOCUMENT_INVALID")
        if len(documents) > 50 or type(case_bindings) is not dict or len(case_bindings) > 40:
            raise ResearchError("AUDIT_INPUT_LIMIT")
        if len(set(case_bindings.values())) != len(case_bindings):
            raise ResearchError("AUDIT_BINDING_DUPLICATE")
        supplied = {}
        total = len(verdict_bytes)
        for d in documents:
            if type(d.key) is not str or type(d.content) is not bytes or len(d.content) > 64 * 1024:
                raise ResearchError("AUDIT_DOCUMENT_INVALID")
            if d.key in supplied:
                raise ResearchError("AUDIT_DOCUMENT_DUPLICATE")
            supplied[d.key] = d.content
            total += len(d.content)
        if total > 256 * 1024 or set(supplied) != set(verdict.references):
            raise ResearchError("AUDIT_DOCUMENT_SET_MISMATCH")
        if run_evidence_key not in supplied:
            raise ResearchError("AUDIT_ANCHOR_MISSING")
        for key, ref in verdict.references.items():
            if sha(supplied[key]) != ref.sha256:
                raise ResearchError("AUDIT_DOCUMENT_HASH_MISMATCH")
        for field in (
            "model_executed",
            "economic_validation",
            "human_paper_review_eligible",
            "audit_activated_paper",
            "demo_orders_sent",
            "live_orders_sent",
        ):
            if type(parse(verdict_bytes).get(field, getattr(verdict, field))) is not bool:
                raise ResearchError("AUDIT_BOOLEAN_INVALID")
        if any(
            type(k) is not str or type(v) is not str or not k or not v
            for k, v in case_bindings.items()
        ):
            raise ResearchError("AUDIT_BINDING_INVALID")
        self._snapshot = canonical(
            {
                "verdict_hex": verdict_bytes.hex(),
                "expected_sha256": expected_sha256,
                "documents": {k: v.hex() for k, v in supplied.items()},
                "case_bindings": case_bindings,
                "run_evidence_key": run_evidence_key,
                "manifest_identity_verified": manifest_identity_verified,
                "history_scope": history_scope,
            }
        ).encode()
        self.fingerprint = identity("PreparedAuditSimulation", parse(self._snapshot))
        self.byte_size = total

    def snapshot(self) -> dict:
        return parse(self._snapshot)

    def verdict(self) -> AuditVerdict:
        return strict_json(bytes.fromhex(self.snapshot()["verdict_hex"]), AuditVerdict)

    def validate_for_graph(self, graph: dict) -> dict:
        saved, v = self.snapshot(), self.verdict()
        run, exp = graph["run"], graph["experiment"]
        if v.audit_status != "COMPLETED_WITH_LIMITATIONS" or v.gates["A"].status != "INTEGRITY_OK":
            raise ResearchError("AUDIT_BLOCKED")
        if (v.run_id, v.experiment_id) != (run["id"], exp["id"]):
            raise ResearchError("AUDIT_LINEAGE_MISMATCH")
        docs = {k: bytes.fromhex(raw) for k, raw in saved["documents"].items()}
        if sha(docs[saved["run_evidence_key"]]) != run["evidence_sha256"]:
            raise ResearchError("AUDIT_RUN_ANCHOR_MISMATCH")
        if any(a["sha256"] not in {sha(raw) for raw in docs.values()} for a in graph["artifacts"]):
            raise ResearchError("ARTIFACT_BYTES_UNAVAILABLE")
        if run["status"] != "COMPLETE" or v.observations.get("runner_status") != "COMPLETE":
            raise ResearchError("PRIMARY_EXECUTION_NOT_COMPLETE")
        if v.observations.get("protocol") != exp["experimental_protocol"]:
            raise ResearchError("AUDIT_PROTOCOL_MISMATCH")
        reference_id = "audit." + saved["expected_sha256"]
        history = _scientific_history(v, reference_id, saved["expected_sha256"])
        try:
            pins = _identity_pins(v, docs, graph)
        except AuditPinConflict as exc:
            exc.evidence_diagnostic["verdict_sha256"] = saved["expected_sha256"]
            raise
        selection = v.observations.get("selection_history", {})
        if type(selection) is not dict:
            raise ResearchError("AUDIT_HISTORY_INVALID")
        if selection.get("holdout_status") != (
            "UNOBSERVED_DECLARED" if exp["holdout"] == "UNOBSERVED" else exp["holdout"]
        ):
            raise ResearchError("AUDIT_HOLDOUT_MISMATCH")
        rows = v.observations.get("native_results")
        if not isinstance(rows, list) or len(rows) > 40:
            raise ResearchError("PRIMARY_RESULTS_INVALID")
        native = {}
        for row in rows:
            key = row.get("backtest_id")
            if type(key) is not str or key in native:
                raise ResearchError("PRIMARY_RESULT_DUPLICATE")
            native[key] = row
        bindings = saved["case_bindings"]
        if set(bindings) != {c["id"] for c in graph["case_results"]} or set(
            bindings.values()
        ) != set(native):
            raise ResearchError("PRIMARY_CASE_SET_MISMATCH")
        for case in graph["case_results"]:
            key = bindings[case["id"]]
            reference = "result:" + key
            if reference not in docs or parse(docs[reference]) != native[key].get("result"):
                raise ResearchError("PRIMARY_RESULT_ANCHOR_MISMATCH")
            result, metadata = native[key]["result"], native[key].get("metadata", {})
            metrics = result.get("metrics", {})
            if metrics.get("backtest_id") != key or metrics.get("status") != "completed":
                raise ResearchError("PRIMARY_RESULT_IDENTITY_MISMATCH")
            mapping = {
                "trades": "closed_trades",
                "net_return_pct": "return_pct",
                "max_drawdown_pct": "max_drawdown_pct",
                "win_rate_pct": "win_rate_pct",
                "profit_factor": "profit_factor",
                "capital_initial": "starting_equity",
            }
            for key in set(mapping.values()) | set(case["metrics"]):
                value = metrics.get(key)
                if value is not None and type(value) not in (int, float):
                    raise ResearchError("PRIMARY_METRIC_TYPE_INVALID")
            if type(metrics.get("closed_trades")) is not int:
                raise ResearchError("PRIMARY_METRIC_TYPE_INVALID")
            if any(metrics.get(source) != case[field] for field, source in mapping.items()):
                raise ResearchError("METRIC_CONTRADICTION")
            if any(metrics.get(k) != val for k, val in case["metrics"].items()):
                raise ResearchError("METRIC_CONTRADICTION")
            if (
                not isinstance(result.get("trades"), list)
                or len(result["trades"]) != case["trades"]
            ):
                raise ResearchError("PRIMARY_TRADES_MISMATCH")
            expected = {
                "symbol": case["asset"],
                "timeframe": case["timeframe"],
                "mode": case["direction"],
                "period": case["segment"],
                "scenario": case["scenario"],
                "costs": case["costs"],
                "parameters": exp["parameters"],
            }
            if any(canonical(metadata.get(k)) != canonical(val) for k, val in expected.items()):
                raise ResearchError("PRIMARY_CONDITIONS_MISMATCH")
            for source, target in (("start", "period_start_utc"), ("end", "period_end_utc")):
                if (
                    source not in metadata
                    or datetime.fromisoformat(metadata[source]).utcoffset() is None
                    or datetime.fromisoformat(metadata[source]).utcoffset().total_seconds() != 0
                    or datetime.fromisoformat(metadata[source])
                    != datetime.fromisoformat(case[target])
                ):
                    raise ResearchError("PRIMARY_PERIOD_MISMATCH")
            segment = case["segment"].casefold()
            period = history["selection_history"].get(segment)
            if segment in {"train", "validation", "test"} and period is not None:
                if datetime.fromisoformat(case["period_start_utc"]) < datetime.fromisoformat(
                    period["start"]
                ) or datetime.fromisoformat(case["period_end_utc"]) > datetime.fromisoformat(
                    period["end"]
                ):
                    history["period_conflicts"].append(
                        {
                            "case_id": case["id"],
                            "segment": segment,
                            "declared_period": period,
                            "observed_period": {
                                "start": case["period_start_utc"],
                                "end": case["period_end_utc"],
                            },
                        }
                    )
        return {
            "reference_id": "audit." + saved["expected_sha256"],
            "run_id": run["id"],
            "audit_id": v.audit_id,
            "sha256": saved["expected_sha256"],
            "status": v.audit_status,
            "verdict": v.auditor_verdict,
            "gates": {k: g.status for k, g in v.gates.items()},
            "limitations": v.blockers + v.uncertainties,
            "scientific_history": history,
            "manifest_identity": _manifest_identity(v, saved, reference_id),
            "identity_pins": pins,
            "verification_scope": "CAPTURED_BYTES_AND_LINEAGE_NOT_A_NEW_ECONOMIC_AUDIT",
        }
