"""Closed declarative claims prevent fabricated metrics without semantic word filters.

ModelReview remains unchanged. Its Text findings carry canonical host observations
or predeclared consultative limitations; arbitrary generated prose is not admitted V1.
"""

from trading_lab_catalog.verification import parse
from trading_lab_orchestration.contracts import canonical

from .context import ResearchError
from .models import identity
from .validator_models import ValidationAssessment, ValidationRequest

CORE = "NO_DECISION: source verdict unchanged; no economic approval or trading authorization"


def prepare_policy(capture: dict) -> dict:
    findings, obligations = [], {}
    references = {r["reference_id"]: r for r in capture["references"]}

    def require(code, text, refs):
        if code not in obligations:
            obligations[code] = {"code": code, "text": text, "references": []}
        obligations[code]["references"] = sorted(set(obligations[code]["references"]) | set(refs))

    audit_refs = [a["reference_id"] for a in capture["primary_audits"]]
    require("NO_DECISION", CORE, audit_refs)
    require(
        "CONSULTATIVE",
        "Consultative simulation; structural validation is not statistical or "
        "economic certification",
        audit_refs,
    )
    require(
        "TECHNICAL_ONLY",
        "COMPLETE describes technical completion, not demonstrated profitability",
        audit_refs,
    )
    require(
        "HASH_NOT_AUDIT",
        "HASH_VERIFIED checks bytes; it does not grant SOURCE_AUDITED or economic validation",
        audit_refs,
    )
    scenario_runs = [
        run
        for run in capture["runs"]
        if any(c["scenario"].upper() in {"BASE", "ADVERSE"} for c in run["cases"])
    ]
    scenarios = {c["scenario"].upper() for run in scenario_runs for c in run["cases"]}
    if scenarios >= {"BASE", "ADVERSE"}:
        # A scenario can occupy a separate run. This warning never asserts that
        # two runs are scientifically equivalent or aggregates their outcomes.
        require(
            "SCENARIOS",
            "BASE and ADVERSE are alternative cost scenarios, not independent trades or samples",
            [run["run_reference_id"] for run in scenario_runs],
        )
    consistency = capture["history_consistency"]
    identity_warning = "Frozen manifest identity consistency: " + canonical(consistency)
    if len(identity_warning) > 4000:
        raise ResearchError("CONTEXT_LIMITATION_LIMIT")
    require("MANIFEST_IDENTITY_CONSISTENCY", identity_warning, audit_refs)
    needs_review = consistency["needs_review"]
    for a in capture["primary_audits"]:
        findings.append(
            canonical(
                {
                    "type": "SOURCE_OBSERVATION",
                    "reference_id": a["reference_id"],
                    "data": {
                        "verdict": a["verdict"],
                        "status": a["status"],
                        "gates": a["gates"],
                        "scientific_history": a["scientific_history"],
                        "identity_pins": a["identity_pins"],
                        "manifest_identity": a["manifest_identity"],
                    },
                }
            )
        )
        history = a["scientific_history"]
        selection = history["selection_history"]
        history_warning = (
            "Scientific selection history: "
            + canonical(
                {
                    "search_history": history["search_history"],
                    "selection_history": selection,
                    "period_conflicts": history["period_conflicts"],
                }
            )
            + "; unknown counters remain null; discovery is not independent OOS validation"
        )
        if len(history_warning) > 4000:
            raise ResearchError("AUDIT_HISTORY_WARNING_LIMIT")
        require("HISTORY." + a["sha256"], history_warning, [a["reference_id"]])
        if history["period_conflicts"]:
            needs_review = True
        pins = a["identity_pins"]
        require(
            "PIN_DOMAINS",
            "Hash domains differ: dataset manifest, data file, resolved configuration and "
            "experiment/run fingerprints are not interchangeable; dataset binding is UNVERIFIED",
            [a["reference_id"]],
        )
        if pins["configuration"]["status"] == "UNVERIFIED_MISSING_SOURCE_PIN":
            require(
                "CONFIGURATION_UNVERIFIED",
                "Resolved configuration has no captured comparable source pin; "
                "identity remains UNVERIFIED",
                [a["reference_id"]],
            )
        elif pins["configuration"]["status"] == "UNVERIFIED_DOMAIN_BINDING":
            require(
                "CONFIGURATION_DOMAIN_UNVERIFIED",
                "Configuration domains have no verified mapping; digest equality or inequality "
                "does not establish scientific equivalence or contradiction",
                [a["reference_id"]],
            )
        for limitation in a["limitations"]:
            require(
                "primary." + identity("AuditLimitation", limitation),
                limitation,
                [a["reference_id"]],
            )
    for run in capture["runs"]:
        ref = run["run_reference_id"]
        if run["audit_status"] != "SOURCE_AUDITED":
            needs_review = True
            require(
                "UNVERIFIED",
                "UNVERIFIED: source accreditation is insufficient and cannot be "
                "supplied by model opinion",
                [ref],
            )
        else:
            require(
                "SOURCE_AUDITED",
                "SOURCE_AUDITED preserves a validated sealed source declaration, not a "
                "new independent economic audit",
                [ref],
            )
        if run["holdout"] != "UNOBSERVED":
            require(
                "HOLDOUT",
                "CONSUMED or UNKNOWN holdout is not independent out-of-sample evidence",
                [ref],
            )
        if run["capital_policy"] == "RESET_PER_SEGMENT":
            require(
                "CAPITAL",
                "RESET_PER_SEGMENT: segment returns must not be concatenated as a "
                "compounded portfolio",
                [ref],
            )
        elif run["capital_policy"] == "UNKNOWN":
            needs_review = True
            require(
                "CAPITAL_UNKNOWN",
                "Capital policy is UNKNOWN; no aggregate portfolio conclusion is supported",
                [ref],
            )
        if not run["cases"]:
            needs_review = True
            require(
                "NO_CASES",
                "No case metrics are available; trade count and statistical "
                "significance remain UNKNOWN",
                [ref],
            )
        for case in run["cases"]:
            cref = case["reference_id"]
            if case["audit_status"] != "SOURCE_AUDITED":
                needs_review = True
                require(
                    "UNVERIFIED",
                    "UNVERIFIED: source accreditation is insufficient and cannot be "
                    "supplied by model opinion",
                    [cref],
                )
            if case["trades"] < 30:
                require(
                    "SAMPLE",
                    "Small trade samples; the descriptive 30-trade threshold is not a "
                    "significance test",
                    [cref],
                )
            require(
                "METRICS",
                "Unavailable metrics remain null/ABSENT; no p-values, confidence "
                "intervals or significance are inferred",
                [cref],
            )
            data = {
                k: case[k]
                for k in (
                    "trades",
                    "net_return_pct",
                    "max_drawdown_pct",
                    "win_rate_pct",
                    "profit_factor",
                    "capital_initial",
                    "costs",
                    "metrics",
                    "metric_availability",
                    "statistical_significance",
                )
            }
            findings.append(
                canonical({"type": "CASE_OBSERVATION", "reference_id": cref, "data": data})
            )
        for d in run["source_decisions"]:
            if d["category"] == "ECONOMIC" and d["verdict"] != "NO_DECISION":
                needs_review = True
                require(
                    "DECISION_CONFLICT",
                    "Catalogue economic declarations differ; the primary NO_DECISION is "
                    "not overwritten",
                    [ref],
                )
    comparison = capture["comparison"]
    if comparison["comparison_status"] == "NOT_COMPARABLE":
        require(
            "COMPARISON",
            "NOT_COMPARABLE: experimental conditions prevent a winner or ranking conclusion",
            list(references),
        )
    else:
        require(
            "COMPARISON",
            "Comparability is not statistical sufficiency, profitability or trading eligibility",
            list(references),
        )
    if len(obligations) > 20:
        raise ResearchError("CONTEXT_LIMITATION_LIMIT")
    return {
        "allowed_findings": findings,
        "obligations": list(obligations.values()),
        "needs_review": needs_review,
        "required_references": audit_refs,
        "allowed_notes": [None, "SIMULATED_CONSULTATION_ONLY"],
    }


def validate_assessment(
    assessment: ValidationAssessment, request: ValidationRequest, capture: dict, policy: dict
) -> None:
    if (
        assessment.request_id != request.request_id
        or assessment.agent_role != "validator"
        or sorted(assessment.source_run_ids) != sorted(request.source_run_ids)
    ):
        raise ResearchError("ASSESSMENT_IDENTITY_MISMATCH")
    refs = {r["reference_id"] for r in capture["references"]}
    cited = set(assessment.model_review.evidence_references)
    if (
        len(cited) != len(assessment.model_review.evidence_references)
        or not cited <= refs
        or not set(policy["required_references"]) <= cited
    ):
        raise ResearchError("INVENTED_OR_MISSING_REFERENCE")
    if (
        any(f not in policy["allowed_findings"] for f in assessment.model_review.findings)
        or not assessment.model_review.findings
    ):
        raise ResearchError("UNSUPPORTED_FINDING_OR_METRIC")
    for f in assessment.model_review.findings:
        if parse(f)["reference_id"] not in cited:
            raise ResearchError("UNCITED_FINDING")
    required = {o["text"] for o in policy["obligations"]}
    if (
        set(assessment.limitations) != required
        or set(assessment.model_review.uncertainties) != required
    ):
        raise ResearchError("LIMITATION_DROPPED_OR_INVENTED")
    for obligation in policy["obligations"]:
        if not cited & set(obligation["references"]):
            raise ResearchError("LIMITATION_REFERENCE_DROPPED")
    if assessment.notes not in policy["allowed_notes"]:
        raise ResearchError("UNSUPPORTED_COMMENTARY")
    if policy["needs_review"] and (
        assessment.status != "NEEDS_REVIEW" or assessment.recommendation == "CONTINUE_RESEARCH"
    ):
        raise ResearchError("SOURCE_CONFIDENCE_ELEVATED")
