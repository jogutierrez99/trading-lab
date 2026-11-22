"""Negative source correspondence tests never repair the primary dossier."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from trading_lab_agents.context import ResearchError
from trading_lab_agents.validator_evidence import AuditDocument, PreparedAudit
from trading_lab_agents.validator_provider import FakeValidatorProvider
from trading_lab_catalog.verification import parse, sha
from trading_lab_orchestration.contracts import canonical

from .test_policy import packet_for


def remake(data, *, verdict=None, documents=None, bindings=None, raw=None):
    documents = documents if documents is not None else data["documents"]
    raw = raw if raw is not None else canonical(verdict or data["verdict"]).encode()
    return PreparedAudit(
        raw,
        expected_sha256=sha(raw),
        documents=tuple(AuditDocument(k, v) for k, v in documents.items()),
        case_bindings=bindings
        if bindings is not None
        else data["source"].snapshot()["case_bindings"],
    )


def anchored(data, source):
    changed = dict(data, sources=(source,))
    changed["request"] = deepcopy(data["request"])
    changed["request"]["audits"][0]["verdict_sha256"] = source.snapshot()["expected_sha256"]
    return changed


def test_verdict_reuses_existing_schema_and_exact_bytes(dossier):
    from trading_lab_orchestration.audit_contracts import AuditVerdict

    assert type(dossier["source"].verdict()) is AuditVerdict
    assert bytes.fromhex(dossier["source"].snapshot()["verdict_hex"]) == dossier["raw_verdict"]
    with pytest.raises(ResearchError, match="AUDIT_HASH_MISMATCH"):
        PreparedAudit(
            dossier["raw_verdict"] + b" ",
            expected_sha256=sha(dossier["raw_verdict"]),
            documents=(),
            case_bindings={},
        )


@pytest.mark.parametrize("mode", ["missing", "changed", "extra", "duplicate"])
def test_captured_documents_are_exact_hash_set(dossier, mode):
    docs = tuple(AuditDocument(k, v) for k, v in dossier["documents"].items())
    if mode == "missing":
        docs = docs[:-1]
    if mode == "changed":
        docs = (AuditDocument(docs[0].key, b"changed"), *docs[1:])
    if mode == "extra":
        docs = (*docs, AuditDocument("unlisted", b"extra"))
    if mode == "duplicate":
        docs = (*docs, docs[0])
    with pytest.raises(ResearchError):
        PreparedAudit(
            dossier["raw_verdict"],
            expected_sha256=sha(dossier["raw_verdict"]),
            documents=docs,
            case_bindings={},
        )


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("run_id", "alien", "AUDIT_SOURCE_SET_MISMATCH"),
        ("experiment_id", "alien", "AUDIT_LINEAGE_MISMATCH"),
        ("audit_id", "alien", "AUDIT_SOURCE_ANCHOR_MISMATCH"),
        ("audit_status", "FAILED", "AUDIT_BLOCKED"),
    ],
)
def test_primary_identities_fail_closed(dossier, exercise, field, value, code):
    verdict = {**dossier["verdict"], field: value}
    data = anchored(dossier, remake(dossier, verdict=verdict))
    result, _, provider, _ = exercise(data)
    assert result["error_code"] == code and provider.calls == 0, result


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("runner_status", "FAILED", "PRIMARY_EXECUTION_NOT_COMPLETE"),
        ("protocol", "other", "AUDIT_PROTOCOL_MISMATCH"),
        ("selection_history", {"holdout_status": "UNOBSERVED_DECLARED"}, "AUDIT_HOLDOUT_MISMATCH"),
        ("native_results", [], "PRIMARY_CASE_SET_MISMATCH"),
    ],
)
def test_primary_conditions_not_silently_reinterpreted(dossier, exercise, field, value, code):
    verdict = deepcopy(dossier["verdict"])
    verdict["observations"][field] = value
    result, _, provider, _ = exercise(anchored(dossier, remake(dossier, verdict=verdict)))
    assert result["error_code"] == code and provider.calls == 0, result


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"return_pct": 99.0}, "METRIC_CONTRADICTION"),
        ({"closed_trades": True}, "PRIMARY_METRIC_TYPE_INVALID"),
        ({"return_pct": "0.5"}, "PRIMARY_METRIC_TYPE_INVALID"),
        ({"profit_factor": 10.0}, "METRIC_CONTRADICTION"),
        ({"backtest_id": "forged"}, "PRIMARY_RESULT_IDENTITY_MISMATCH"),
    ],
)
def test_catalogue_metrics_must_match_captured_primary(fixture_factory, exercise, changes, code):
    data = fixture_factory(metric_updates={"c1": changes})
    result, _, provider, _ = exercise(data)
    assert result["error_code"] == code and provider.calls == 0, result


def test_ambiguous_case_binding_rejected(dossier):
    with pytest.raises(ResearchError, match="AUDIT_BINDING_DUPLICATE"):
        remake(dossier, bindings={"c1": "c1", "c2": "c1"})


@pytest.mark.parametrize("field", ["economic_validation", "demo_orders_sent", "model_executed"])
def test_numeric_false_in_primary_rejected(dossier, field):
    verdict = {**dossier["verdict"], field: 0}
    # The historical bool field rejects before the wrapper; Literal[False]
    # fields need the wrapper's additional exact-type guard.
    with pytest.raises(ValueError):
        remake(dossier, verdict=verdict)


@pytest.mark.parametrize(
    "case_changes,reason",
    [
        ({"period_start_utc": datetime(2024, 1, 2, tzinfo=UTC)}, "period_start_utc"),
        ({"capital_initial": 20000.0}, "capital_initial"),
        ({"costs": {"trading_fee_pct": 0.5}}, "costs"),
        ({"scenario": "stress"}, "scenario"),
    ],
)
def test_v04_real_comparator_retains_condition_differences(
    fixture_factory, exercise, case_changes, reason
):
    data = fixture_factory(
        comparable=True, paired=True, second_updates={"case_updates": {0: case_changes}}
    )
    result, _, _, book = exercise(data)
    assert result["status"] == "COMPLETE", result
    comparison = packet_for(data, book)["catalogue"]["comparison"]
    assert comparison["comparison_status"] == "NOT_COMPARABLE"
    assert reason in comparison["condition_differences"] and comparison["winner"] is None


def test_comparable_does_not_mean_statistically_valid(fixture_factory, exercise):
    data = fixture_factory(comparable=True, paired=True, holdout="UNOBSERVED", trades=40)
    result, _, _, book = exercise(data)
    assert result["status"] == "COMPLETE", result
    assert packet_for(data, book)["catalogue"]["comparison"]["comparison_status"] == "COMPARABLE"
    assert any("Comparability is not statistical" in s for s in result["assessment"]["limitations"])
    assert result["assessment"]["model_review"]["verdict"] == "NO_DECISION"


def test_no_cases_preserves_unknown_sample(fixture_factory, exercise):
    data = fixture_factory(cases=False)
    result, _, _, book = exercise(data)
    assert result["status"] == "COMPLETE", result
    assert result["assessment"]["status"] == "NEEDS_REVIEW"
    assert packet_for(data, book)["catalogue"]["runs"][0]["cases"] == []
    assert any("trade count" in s and "UNKNOWN" in s for s in result["assessment"]["limitations"])


def test_unverified_source_cannot_self_upgrade(fixture_factory, exercise):
    data = fixture_factory(source_audited=False)
    first, *_ = exercise(data)
    a = first["assessment"]
    a["status"] = "CONSULTATIVE"
    a["recommendation"] = "CONTINUE_RESEARCH"
    result, *_ = exercise(data, provider=FakeValidatorProvider(response=canonical(a).encode()))
    assert result["error_code"] == "SOURCE_CONFIDENCE_ELEVATED"


def test_gate_a_failure_never_invokes_provider(dossier, exercise):
    verdict = deepcopy(dossier["verdict"])
    verdict["gates"]["A"]["status"] = "INTEGRITY_FAIL"
    result, _, provider, _ = exercise(anchored(dossier, remake(dossier, verdict=verdict)))
    assert result["error_code"] == "AUDIT_BLOCKED" and provider.calls == 0


def test_captured_source_snapshots_detached(dossier):
    snapshot = dossier["source"].snapshot()
    snapshot["expected_sha256"] = "0" * 64
    assert dossier["source"].snapshot()["expected_sha256"] == sha(dossier["raw_verdict"])
    assert parse(dossier["raw_verdict"])["auditor_verdict"] == "NO_DECISION"
